import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from game.catalog import default_questions_path, load_questions
from game.engine import ReplyKind
from game.expression import expression_payload, valid_lead
from game.models import Difficulty, normalize_answer
from game.service import GameService


class GameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "game.db"
        self.catalog = load_questions(default_questions_path())
        self.now = 10000
        self.game = self.service()
        self.n = 0

    def service(self, **kw):
        return GameService(self.path, self.catalog, clock=lambda: self.now, **kw)

    def send(self, text, session="qq:group:1", mid=None, admin=False):
        self.n += 1
        return self.game.handle(session, mid or str(self.n), "u", text, admin=admin)

    def current(self, session="qq:group:1"):
        return self.catalog.get(self.game.state(session)["current_subject_id"])

    def test_bundled_catalog(self):
        self.assertEqual(self.catalog.size, 30)
        self.assertEqual(
            {d: sum(q.difficulty == d for q in self.catalog.questions) for d in Difficulty},
            {Difficulty.EASY: 12, Difficulty.NORMAL: 12, Difficulty.HARD: 6},
        )

    def test_full_flow(self):
        start = self.send("/猜动画 开始")
        self.assertEqual(start.reply.kind, ReplyKind.QUESTION)
        question = self.current()
        for i in range(3):
            hint = self.send("/猜动画 提示")
            self.assertEqual(hint.reply.hint, question.hints[i])
        self.assertEqual(self.send("/猜动画 提示").reply.kind, ReplyKind.HINTS_EXHAUSTED)
        self.assertEqual(self.send("我猜 绝不可能的答案").reply.kind, ReplyKind.WRONG_ANSWER)
        self.assertEqual(
            self.send(question.aliases[0] if question.aliases else question.title).reply.kind,
            ReplyKind.CORRECT_ANSWER,
        )

    def test_plain_chat_is_not_consumed_during_game(self):
        self.send("/猜动画 开始")
        before = self.game.state("qq:group:1")
        self.assertFalse(self.send("晚上大家要不要一起吃饭？").consumed)
        self.assertFalse(self.send("我猜你今天晚上要加班吧").consumed)
        self.assertEqual(self.game.state("qq:group:1"), before)

    def test_natural_hint_is_game_not_chat(self):
        self.send("/猜动画 开始")
        for phrase, level in [("提示", 1), ("提示一下", 2), ("给点提示", 3)]:
            result = self.send(phrase)
            self.assertTrue(result.consumed)
            self.assertEqual(result.reply.kind, ReplyKind.HINT)
            self.assertEqual(result.reply.hint_level, level)

    def test_natural_controls_only_inside_active_game(self):
        for phrase in ("提示", "答案", "暂停", "下一题"):
            self.assertFalse(self.send(phrase).consumed)
        self.send("/猜动画 开始")
        self.assertEqual(self.send("下一题").reply.kind, ReplyKind.QUESTION)
        self.assertEqual(self.send("答案").reply.kind, ReplyKind.REVEALED)
        self.assertFalse(self.send("提示").consumed)

    def test_shortcuts_can_still_be_explicitly_disabled(self):
        self.game = self.service(shortcuts=False)
        self.send("/猜动画 开始")
        self.assertFalse(self.send("提示").consumed)
        self.assertEqual(self.send("/猜动画 提示").reply.kind, ReplyKind.HINT)

    def test_known_wrong_title_is_an_answer(self):
        self.send("/猜动画 开始")
        wrong = next(q for q in self.catalog.questions if q.subject_id != self.current().subject_id)
        self.assertEqual(self.send(wrong.title).reply.kind, ReplyKind.WRONG_ANSWER)

    def test_guess_does_not_execute_a_command(self):
        self.send("/猜动画 开始")
        self.assertEqual(self.send("我猜 提示").reply.kind, ReplyKind.WRONG_ANSWER)
        self.assertEqual(self.game.state("qq:group:1")["hint_level"], 0)

    def test_persisted_dedup_after_restart(self):
        self.send("/猜动画 开始", mid="same")
        old = self.current()
        self.game = self.service()
        duplicate = self.send("/猜动画 开始", mid="same")
        self.assertTrue(duplicate.duplicate)
        self.assertFalse(duplicate.messages)
        self.assertEqual(self.current(), old)

    def test_answer_duplicate_stays_consumed_after_win(self):
        self.send("/猜动画 开始")
        title = self.current().title
        self.send(title, mid="win")
        self.assertTrue(self.send(title, mid="win").duplicate)

    def test_group_isolation_and_same_message_ids(self):
        self.send("/猜动画 开始", mid="1")
        self.assertFalse(self.send("我猜 随便", session="qq:group:2").consumed)
        other = self.send("/猜动画 开始", session="qq:group:2", mid="1")
        self.assertFalse(other.duplicate)

    def test_hint_progress_survives_restart(self):
        self.send("/猜动画 开始")
        self.send("/猜动画 提示")
        self.game = self.service()
        self.assertEqual(self.send("/猜动画 提示").reply.hint_level, 2)

    def test_difficulty_and_pause(self):
        for level, expected in [
            ("简单", Difficulty.EASY),
            ("困难", Difficulty.HARD),
            ("普通", Difficulty.NORMAL),
        ]:
            result = self.send("/猜动画 难度 " + level)
            self.assertEqual(result.reply.question.difficulty, expected)
        self.assertEqual(self.send("/猜动画 暂停").reply.kind, ReplyKind.PAUSED)
        self.assertFalse(self.send("我猜 轻音少女").consumed)

    def test_timeout_once_and_after_restart(self):
        self.send("/猜动画 开始")
        self.now += 901
        self.game = self.service()
        self.assertTrue(self.game.expire("qq:group:1").messages)
        self.assertFalse(self.game.expire("qq:group:1").messages)

    def test_late_answer_cannot_win_between_timer_ticks(self):
        self.send("/猜动画 开始")
        title = self.current().title
        self.now += 901
        self.assertEqual(self.send(title).reply.kind, ReplyKind.REVEALED)

    def test_timeout_disabled(self):
        self.game = self.service(timeout=0)
        self.send("/猜动画 开始")
        self.now += 100000
        self.assertFalse(self.game.expire("qq:group:1").messages)

    def test_concurrent_answers_only_one_winner(self):
        self.send("/猜动画 开始")
        title = self.current().title
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(lambda i: self.game.handle("qq:group:1", f"answer{i}", "u", title), range(8))
            )
        self.assertEqual(
            sum(r.reply is not None and r.reply.kind is ReplyKind.CORRECT_ANSWER for r in results), 1
        )

    def test_admin_clear_is_scoped(self):
        self.send("/猜动画 开始")
        self.send("/猜动画 开始", session="qq:group:2")
        self.send("/猜动画 清空")
        self.assertTrue(self.current())
        self.send("/猜动画 清空", admin=True)
        self.assertEqual(self.game.state("qq:group:1"), {})
        self.assertTrue(self.game.state("qq:group:2"))

    def test_shortcuts_only_during_active_game(self):
        self.game = self.service(shortcuts=True)
        self.assertFalse(self.send("来一个").consumed)
        self.send("/猜动画 开始")
        self.assertEqual(self.send("提示").reply.kind, ReplyKind.HINT)

    def test_namespace_boundary(self):
        self.assertFalse(self.send("/猜动画家").consumed)
        self.assertTrue(self.send("猜动画 帮助").consumed)

    def test_normalization(self):
        self.assertEqual(normalize_answer(" ＳＴＥＩＮＳ；ＧＡＴＥ "), normalize_answer("Steins Gate"))

    def test_ai_payload_has_no_answer_or_hint(self):
        result = self.send("/猜动画 开始")
        payload = expression_payload(result.reply)
        self.assertEqual(set(payload), {"event", "hint_level"})
        self.assertNotIn(result.reply.question.title, json.dumps(payload, ensure_ascii=False))
        self.assertFalse(valid_lead(result.reply.question.title, result.reply))
        self.assertTrue(valid_lead("下一道挑战准备好啦。", result.reply))

    def test_malformed_and_duplicate_packs_rejected(self):
        raw = json.loads(default_questions_path().read_text(encoding="utf-8"))
        target = Path(self.temp.name) / "custom.json"
        for data in ([raw[0], raw[0]], [{**raw[0], "hints": "abc"}], [{**raw[0], "aliases": "abc"}], []):
            target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_questions(target)

    def test_no_immediate_repeat_when_recent_pool_exhausted(self):
        for _ in range(30):
            previous = self.current().subject_id if self.game.state("qq:group:1") else None
            result = self.send("/猜动画 难度 困难")
            self.assertNotEqual(result.reply.question.subject_id, previous)

    def test_status_does_not_expose_answer(self):
        self.send("/猜动画 开始")
        result = self.send("/猜动画 状态")
        self.assertNotIn(self.current().title, "\n".join(result.messages))

    def test_state_rollback_is_atomic(self):
        from unittest.mock import patch

        with patch("game.service.AnimePartyEngine.handle", side_effect=RuntimeError("test")):
            with self.assertRaises(RuntimeError):
                self.send("/猜动画 开始", mid="retry")
        self.assertFalse(self.send("/猜动画 开始", mid="retry").duplicate)


if __name__ == "__main__":
    unittest.main()
