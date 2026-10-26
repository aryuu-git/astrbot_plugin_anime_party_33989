import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from game.catalog import QuestionCatalog
from game.generation import object_from_text, puzzle_from_object, generate_question
from game.service import GameService

SOURCE = {"title": "动态测试作品", "names": ["动态测试作品"], "id": 999, "summary": "仅为测试资料"}
DATA = {
    "rows": [
        ["🧑‍🔬", "🧪", "📱", "🍌", "⚡"],
        ["🏙️", "💻", "📧", "⏪", "⏳", "🔁", "🦋"],
        ["👥", "🌍", "🔀", "🚪", "🕰️"],
    ],
    "hints": ["涉及时间", "舞台是一座城市", "主角会接触实验设备"],
    "explanation": "几组图标展示舞台与道具。",
}


class GenerationTests(unittest.IsolatedAsyncioTestCase):
    def test_exact_grid_and_unicode_sequences(self):
        q = puzzle_from_object(DATA, SOURCE, "normal")
        self.assertEqual([len(r.split()) for r in q.emoji.splitlines()], [5, 7, 5])
        altered = json.loads(json.dumps(DATA))
        altered["rows"][0][0] = "👨‍👩‍👧‍👦"
        puzzle_from_object(altered, SOURCE, "normal")
        for bad in ("😀😀", "abc", "5", "🧪 🧪"):
            altered["rows"][0][0] = bad
            with self.assertRaises(ValueError):
                puzzle_from_object(altered, SOURCE, "normal")

    def test_wrong_count_and_title_leak_rejected(self):
        d = json.loads(json.dumps(DATA))
        d["rows"][1].pop()
        with self.assertRaises(ValueError):
            puzzle_from_object(d, SOURCE, "normal")
        d = json.loads(json.dumps(DATA))
        d["hints"][0] = "就是动态测试作品"
        with self.assertRaises(ValueError):
            puzzle_from_object(d, SOURCE, "normal")

    def test_json_fences_and_invalid_json(self):
        self.assertEqual(object_from_text('```json\n{"a":1}\n```'), {"a": 1})
        with self.assertRaises(ValueError):
            object_from_text("not JSON")

    async def test_dynamic_generate_verifies_title(self):
        ctx = SimpleNamespace(
            llm_generate=AsyncMock(
                side_effect=[
                    SimpleNamespace(completion_text=json.dumps({"titles": ["动态测试作品"]})),
                    SimpleNamespace(completion_text=json.dumps(DATA)),
                ]
            )
        )
        with patch("game.generation.verify_title", return_value=SOURCE) as verify:
            q = await generate_question(ctx, "existing", "normal", [])
        self.assertEqual(q.title, SOURCE["title"])
        verify.assert_called_once()

    async def test_invalid_grid_retried_but_not_cached(self):
        d = json.loads(json.dumps(DATA))
        d["rows"][0].pop()
        ctx = SimpleNamespace(
            llm_generate=AsyncMock(
                side_effect=[
                    SimpleNamespace(completion_text=json.dumps({"titles": ["动态测试作品"]})),
                    SimpleNamespace(completion_text=json.dumps(d)),
                    SimpleNamespace(completion_text=json.dumps(d)),
                ]
            )
        )
        with patch("game.generation.verify_title", return_value=SOURCE):
            with self.assertRaises(ValueError):
                await generate_question(ctx, "existing", "normal", [])

    def test_empty_runtime_no_static_fallback_and_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "dynamic.db"
            service = GameService(p, QuestionCatalog([], allow_empty=True), require_generation=True)
            self.assertEqual(service.catalog.size, 0)
            self.assertIn("未生成", service.handle("s", "no-ready", "u", "/猜动画 开始").messages[0])
            q = puzzle_from_object(DATA, SOURCE, "normal")
            service.register_generated(q)
            result = service.handle("s", "new", "u", "/猜动画 开始", prepared_question=q)
            self.assertEqual(result.reply.question.subject_id, q.subject_id)
            again = GameService(p, QuestionCatalog([], allow_empty=True), require_generation=True)
            self.assertEqual(again.handle("s", "hint", "u", "提示").reply.hint_level, 1)
            # Historical generated puzzles may restore a live round but never supply a new round.
            self.assertIn("未生成", again.handle("s", "next", "u", "下一题").messages[0])
            self.assertEqual(again.recent_titles(), [q.title])

    def test_generation_request_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as temp:
            s = GameService(
                Path(temp) / "x.db", QuestionCatalog([], allow_empty=True), require_generation=True
            )
            self.assertEqual(s.generation_request("s", "m", "/猜动画 难度 简单"), "easy")
            q = puzzle_from_object(DATA, SOURCE, "easy")
            s.register_generated(q)
            s.handle("s", "m", "u", "/猜动画 难度 简单", prepared_question=q)
            self.assertIsNone(s.generation_request("s", "m", "/猜动画 难度 简单"))
