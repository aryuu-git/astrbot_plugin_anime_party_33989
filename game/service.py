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
        shortcuts=True,
        require_generation=False,
        clock=time.time,
    ):
        self.path, self.catalog, self.clock = path, catalog, clock
        self.timeout, self.recent_limit = max(0, timeout), max(0, recent_limit)
        self.plain_answers, self.shortcuts = plain_answers, shortcuts
        self.require_generation = require_generation
        self.presenter = ChineseGamePresenter(Random())
        self.known_answers = {
            normalize_answer(name) for q in catalog.questions for name in (q.title, *q.aliases)
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn, conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError(f"不支持的游戏数据库版本：{version}")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS state(namespace TEXT, session TEXT, "
                "value TEXT NOT NULL, PRIMARY KEY(namespace,session))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS handled(session TEXT, message TEXT, "
                "created REAL NOT NULL, PRIMARY KEY(session,message))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL)"
            )
            conn.execute("PRAGMA user_version=2")
            for (payload,) in conn.execute("SELECT payload FROM questions"):
                self.catalog.add(self._decode_question(json.loads(payload)))
        self._refresh_answers()

    def _refresh_answers(self):
        self.known_answers = {
            normalize_answer(n) for q in self.catalog.questions for n in (q.title, *q.aliases)
        }

    @staticmethod
    def _decode_question(data):
        from .models import Question, Difficulty

        return Question(
            data["subject_id"],
            data["title"],
            tuple(data["aliases"]),
            data["emoji"],
            Difficulty(data["difficulty"]),
            tuple(data["hints"]),
            data["explanation"],
            source_subject_id=data.get("source_subject_id"),
        )

    def register_generated(self, question):
        from dataclasses import asdict

        with closing(self.connect()) as conn, conn:
            conn.execute(
                "INSERT OR IGNORE INTO questions VALUES(?,?,?)",
                (question.subject_id, json.dumps(asdict(question), ensure_ascii=False), self.clock()),
            )
        self.catalog.add(question)
        self._refresh_answers()

    def recent_titles(self):
        with closing(self.connect()) as conn:
            return [
                json.loads(row[0])["title"]
                for row in conn.execute(
                    "SELECT payload FROM questions ORDER BY created DESC,id DESC LIMIT 12"
                )
            ]

    @staticmethod
    def _is_start(action):
        return action in (
            AnimePartyEngine.START_COMMANDS
            | AnimePartyEngine.NEXT_COMMANDS
            | AnimePartyEngine.EASY_COMMANDS
            | AnimePartyEngine.NORMAL_COMMANDS
            | AnimePartyEngine.HARD_COMMANDS
        )

    def generation_request(self, session, message_id, text):
        with closing(self.connect()) as conn:
            if conn.execute(
                "SELECT 1 FROM handled WHERE session=? AND message=?", (session, message_id)
            ).fetchone():
                return None
        state = self.state(session)
        action = self._route(text, state)
        if not self._is_start(action):
            return None
        if action in AnimePartyEngine.EASY_COMMANDS:
            return "easy"
        if action in AnimePartyEngine.HARD_COMMANDS:
            return "hard"
        if action in AnimePartyEngine.NORMAL_COMMANDS:
            return "normal"
        return state.get("difficulty", "normal")

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
            conversational = {
                "提示一下": "提示",
                "给点提示": "提示",
                "再提示一下": "提示",
                "来点提示": "提示",
                "换一个": "下一题",
                "换一题": "下一题",
                "揭晓": "公布答案",
            }
            if text in conversational:
                return conversational[text]
            if text in (
                "来一个",
                "再来",
                "下一题",
                "提示",
                "给个提示",
                "公布答案",
                "答案",
                "公布",
                "暂停",
                "不玩了",
                "简单点",
                "简单",
                "难一点",
                "困难",
                "普通",
            ):
                return text
        if self.plain_answers and normalize_answer(text) in self.known_answers:
            return "@guess:" + text
        return None

    def handle(self, session, message_id, sender, text, *, admin=False, prepared_question=None):
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
            if self.require_generation and self._is_start(action) and prepared_question is None:
                return Outcome(True, ("新题尚未生成，请重新发 /猜动画 开始。",))
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
                    line += f"：\n{q.emoji}\n已用提示 {state.get('hint_level', 0)}/3"
                return Outcome(True, (line,))
            if action == "@clear":
                if not admin:
                    return Outcome(True, ("只有 AstrBot 管理员可以清空当前会话游戏状态。",))
                conn.execute("DELETE FROM state WHERE namespace='anime-party' AND session=?", (session,))
                return Outcome(True, ("已清空当前会话游戏状态。",))
            engine = self._engine(conn)
            engine.next_question = prepared_question
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
