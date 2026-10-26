"""Adapter behavior tests with fake transport; real AstrBot import is checked on deployment."""

import asyncio
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_adapter():
    class Star:
        def __init__(self, context):
            self.context = context

    tools = SimpleNamespace(get_data_dir=MagicMock())

    def decorator(*a, **kw):
        return lambda target: target

    modules = {
        "astrbot": types.ModuleType("astrbot"),
        "astrbot.api": SimpleNamespace(logger=MagicMock()),
        "astrbot.api.event": SimpleNamespace(
            AstrMessageEvent=object,
            MessageChain=object,
            filter=SimpleNamespace(event_message_type=decorator, EventMessageType=SimpleNamespace(ALL=0)),
        ),
        "astrbot.api.star": SimpleNamespace(Context=object, Star=Star, StarTools=tools, register=decorator),
    }
    spec = importlib.util.spec_from_file_location(
        "party_test_adapter", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location("party_test_adapter.main", ROOT / "main.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, tools


ADAPTER, TOOLS = load_adapter()


class Event:
    def __init__(self, text, mid="1", session="qq:group:1", segments=()):
        self.message_str, self.unified_msg_origin = text, session
        self.message_obj = SimpleNamespace(message_id=mid)
        self.segments, self.extra, self.stopped = segments, {}, False

    def get_sender_id(self):
        return "user"

    def get_self_id(self):
        return "bot"

    def get_messages(self):
        return self.segments

    def get_platform_name(self):
        return "aiocqhttp"

    def is_admin(self):
        return True

    def set_extra(self, key, value):
        self.extra[key] = value

    def stop_event(self):
        self.stopped = True

    def plain_result(self, text):
        return text


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        TOOLS.get_data_dir.return_value = Path(self.temp.name)
        self.context = SimpleNamespace(
            get_current_chat_provider_id=AsyncMock(return_value="existing-provider"),
            llm_generate=AsyncMock(return_value=SimpleNamespace(completion_text="准备好下一道挑战吧。")),
        )
        self.plugin = ADAPTER.AnimePartyPlugin(self.context, {"allowed_sessions": ["qq:group:1"]})

    async def run_event(self, event):
        return [line async for line in self.plugin.on_message(event)]

    async def test_consumed_game_event_stops_other_chat_handlers(self):
        event = Event("猜动画 开始")
        self.assertEqual(len(await self.run_event(event)), 1)
        self.assertTrue(event.stopped)
        self.assertTrue(event.extra["anime_party_consumed"])
        self.context.llm_generate.assert_not_awaited()

    async def test_hint_is_consumed_before_regular_chat(self):
        await self.run_event(Event("/猜动画 开始", mid="start"))
        event = Event("提示", mid="hint")
        result = await self.run_event(event)
        self.assertTrue(event.stopped)
        self.assertIn("提示 1/3", result[0])
        self.context.llm_generate.assert_not_awaited()

    async def test_plain_chat_and_other_session_pass_through(self):
        for event in [Event("晚上吃什么"), Event("/猜动画 开始", session="qq:group:other")]:
            self.assertEqual(await self.run_event(event), [])
            self.assertFalse(event.stopped)

    async def test_empty_allowlist_denies_all(self):
        self.plugin.config["allowed_sessions"] = []
        self.assertEqual(await self.run_event(Event("/猜动画 开始")), [])

    async def test_directed_to_other_person_passes_through(self):
        segment = type("At", (), {"qq": "someone-else"})()
        event = Event("/猜动画 开始", segments=[segment])
        self.assertEqual(await self.run_event(event), [])
        self.assertFalse(event.stopped)

    async def test_ai_inherits_provider_and_immutable_question(self):
        self.plugin.config["ai_expression"] = True
        self.plugin._persona = AsyncMock(return_value="会话实际人格")
        lines = await self.run_event(Event("/猜动画 开始"))
        self.assertIn("猜猜这部动画", lines[0])
        self.assertIn("准备好下一道挑战吧", lines[0])
        call = self.context.llm_generate.call_args.kwargs
        self.assertEqual(call["chat_provider_id"], "existing-provider")
        self.assertIn("会话实际人格", call["system_prompt"])
        self.assertEqual(set(json.loads(call["prompt"])), {"event", "hint_level"})

    async def test_model_failure_falls_back_to_game(self):
        self.plugin.config["ai_expression"] = True
        self.plugin._persona = AsyncMock(return_value="")
        self.context.llm_generate.side_effect = RuntimeError("provider offline")
        lines = await self.run_event(Event("/猜动画 开始"))
        self.assertTrue(lines[0].startswith("猜猜这部动画"))

    async def test_model_timeout_falls_back(self):
        self.plugin.config.update(ai_expression=True, ai_timeout_seconds=0.01)
        self.plugin._persona = AsyncMock(return_value="")
        self.context.llm_generate.side_effect = lambda **kw: None

        async def slow(**kw):
            await asyncio.sleep(10)

        self.context.llm_generate.side_effect = slow
        lines = await self.run_event(Event("/猜动画 开始"))
        self.assertTrue(lines[0].startswith("猜猜这部动画"))

    async def test_duplicate_event_suppresses_chat_after_reload(self):
        await self.run_event(Event("/猜动画 开始", mid="same"))
        self.plugin = ADAPTER.AnimePartyPlugin(self.context, self.plugin.config)
        event = Event("/猜动画 开始", mid="same")
        self.assertEqual(await self.run_event(event), [])
        self.assertTrue(event.stopped)

    async def test_session_persona_binding_is_resolved(self):
        self.context.conversation_manager = SimpleNamespace(
            get_curr_conversation_id=AsyncMock(return_value="cid"),
            get_conversation=AsyncMock(return_value=SimpleNamespace(persona_id="session-persona")),
        )
        resolver = AsyncMock(return_value=("bound", {"prompt": "绑定人格"}, None, False))
        self.context.persona_manager = SimpleNamespace(resolve_selected_persona=resolver)
        self.context.get_config = lambda umo: {"provider_settings": {}}
        self.assertEqual(await self.plugin._persona(Event("x")), "绑定人格")
        self.assertEqual(resolver.call_args.kwargs["conversation_persona_id"], "session-persona")


if __name__ == "__main__":
    unittest.main()
