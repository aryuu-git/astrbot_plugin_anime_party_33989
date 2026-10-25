"""Explicit routing and transactional persistence; never captures ordinary chat."""

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from random import Random

from .catalog import QuestionCatalog
from .engine import AnimePartyEngine, GameReply, GameStatus, ReplyKind
from .models import normalize_answer
from .presentation import ChineseGamePresenter
from .types import IncomingMessage

HELP = (
    "Emoji 猜动画\n"
    "/猜动画 开始｜下一题｜提示｜答案｜暂停｜状态\n"
    "/猜动画 难度 简单/普通/困难\n"
    "开局后发送“我猜 动画名”，或直接发送题库中的作品名/别名。\n"
    "普通聊天不会被当成错答；/猜动画 清空 需管理员权限。"
)


@dataclass(frozen=True)
class Outcome:
    consumed: bool = False
    messages: tuple[str, ...] = ()
    reply: GameReply | None = None
    duplicate: bool = False


class SQLState:
    def __init__(self, conn):
        self.conn = conn

    def get(self, namespace, key):
        row = self.conn.execute(
            "SELECT value FROM state WHERE namespace=? AND session=?", (namespace, key)
        ).fetchone()
        return row[0] if row else None

    def set(self, namespace, key, value):
        self.conn.execute(
            "INSERT OR REPLACE INTO state(namespace,session,value) VALUES(?,?,?)",
            (namespace, key, value),
        )


class GameService:
    def __init__(
        self,
        path: Path,
        catalog: QuestionCatalog,
        *,
        timeout=900,
        recent_limit=8,
        plain_answers=True,
        shortcuts=False,
        clock=time.time,
    ):
        self.path, self.catalog, self.clock = path, catalog, clock
        self.timeout, self.recent_limit = max(0, timeout), max(0, recent_limit)
        self.plain_answers, self.shortcuts = plain_answers, shortcuts
        self.presenter = ChineseGamePresenter(Random())
        self.known_answers = {
            normalize_answer(name) for q in catalog.questions for name in (q.title, *q.aliases)
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn, conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError(f"不支持的游戏数据库版本：{version}")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS state(namespace TEXT, session TEXT, "
                "value TEXT NOT NULL, PRIMARY KEY(namespace,session))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS handled(session TEXT, message TEXT, "
                "created REAL NOT NULL, PRIMARY KEY(session,message))"
            )
            conn.execute("PRAGMA user_version=1")

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def state(self, session):
        with closing(self.connect()) as conn:
            raw = SQLState(conn).get("anime-party", session)
        return json.loads(raw) if raw else {}

    def sessions(self):
        with closing(self.connect()) as conn:
            return [r[0] for r in conn.execute("SELECT session FROM state WHERE namespace='anime-party'")]

    def _engine(self, conn):
        # Fresh per transaction: rolled-back or concurrent calls cannot leave stale caches.
        return AnimePartyEngine(
            self.catalog,
            state_store=SQLState(conn),
            recent_limit=self.recent_limit,
            round_timeout_seconds=0,
            name_triggers=(),
            clock=self.clock,
        )

    def _route(self, text, state):
        text = text.strip()
        explicit = text == "猜动画" or text.startswith("猜动画 ")
        if text.startswith("/猜动画"):
            tail = text[len("/猜动画") :]
            explicit = not tail or tail[0].isspace()
            if not explicit:
                return None
            text = "猜动画" + tail
        if explicit:
            action = text[len("猜动画") :].strip()
            aliases = {
                "": "@help",
                "帮助": "@help",
                "状态": "@status",
                "清空": "@clear",
                "开始": "来一个",
                "下一题": "下一题",
                "提示": "提示",
                "答案": "公布答案",
                "公布答案": "公布答案",
                "暂停": "暂停",
            }
            if action.startswith("难度 "):
                level = action[3:].strip()
                return {"简单": "简单点", "普通": "普通", "困难": "困难"}.get(level, "@help")
            if action.startswith("我猜 "):
                return "@guess:" + action[3:].strip()
            return aliases.get(action, "@help")
        active = state.get("status") == GameStatus.ACTIVE
        if not active:
            return None
        if text.startswith(("我猜 ", "我猜：", "我猜:")):
            guess = text[2:].lstrip(" ：:")
            return "@guess:" + guess if guess else None
        if self.shortcuts:
            if text in (
                "来一个",
                "再来",
                "下一题",
                "提示",
                "给个提示",
                "公布答案",
                "暂停",
                "简单点",
                "难一点",
                "普通",
            ):
                return text
        if self.plain_answers and normalize_answer(text) in self.known_answers:
            return "@guess:" + text
        return None

    def handle(self, session, message_id, sender, text, *, admin=False):
        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM handled WHERE session=? AND message=?", (session, message_id)
            ).fetchone():
                return Outcome(consumed=True, duplicate=True)
            raw = SQLState(conn).get("anime-party", session)
            state = json.loads(raw) if raw else {}
            action = self._route(text, state)
            if action is None:
                return Outcome()
            conn.execute("INSERT INTO handled VALUES(?,?,?)", (session, message_id, self.clock()))
            conn.execute(
                "DELETE FROM handled WHERE rowid IN "
                "(SELECT rowid FROM handled ORDER BY created DESC,rowid DESC LIMIT -1 OFFSET 4096)"
            )
            if action == "@help":
                return Outcome(True, (HELP,))
            if action == "@status":
                active = state.get("status") == GameStatus.ACTIVE
                q = self.catalog.get(state.get("current_subject_id")) if active else None
                line = "进行中" if active else "暂无进行中的题目"
                if q:
                    line += f"：{q.emoji}，已用提示 {state.get('hint_level', 0)}/3"
                return Outcome(True, (line,))
            if action == "@clear":
                if not admin:
                    return Outcome(True, ("只有 AstrBot 管理员可以清空当前会话游戏状态。",))
                conn.execute("DELETE FROM state WHERE namespace='anime-party' AND session=?", (session,))
                return Outcome(True, ("已清空当前会话游戏状态。",))
            engine = self._engine(conn)
            game = engine._get_session(session)
            if (
                self.timeout > 0
                and game.status is GameStatus.ACTIVE
                and game.started_at is not None
                and self.clock() - game.started_at >= self.timeout
            ):
                expired = engine._reveal(game)
                engine._persist(session, game, expired)
                # An answer after the deadline cannot win, even between timer ticks.
                if action.startswith("@guess:") or action == "提示":
                    return Outcome(True, ("本题时间到。" + self.presenter.render(expired)[0],), expired)
            if action.startswith("@guess:"):
                # Explicit guesses bypass command words: "我猜 提示" is not a hint request.
                game = engine._get_session(session)
                reply = engine._answer(game, action[7:])
                reply = engine._persist(session, game, reply)
                if reply.kind is ReplyKind.IGNORED:
                    return Outcome(True, ("当前没有进行中的题目，先发 /猜动画 开始。",))
            else:
                reply = engine.handle(IncomingMessage(message_id, session, sender, action))
            return Outcome(True, self.presenter.render(reply), reply)

    def expire(self, session):
        if self.timeout <= 0:
            return Outcome()
        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            engine = self._engine(conn)
            game = engine._get_session(session)
            if (
                game.status is not GameStatus.ACTIVE
                or game.started_at is None
                or self.clock() - game.started_at < self.timeout
            ):
                return Outcome()
            reply = engine._reveal(game)
            engine._persist(session, game, reply)
            return Outcome(True, ("本题时间到。" + self.presenter.render(reply)[0],), reply)
