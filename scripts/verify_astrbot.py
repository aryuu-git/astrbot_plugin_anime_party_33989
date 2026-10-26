"""Run inside an AstrBot environment; uses real events/stage, no platform sends.

Usage: python verify_astrbot.py /path/to/parent/of/plugin-directory
"""

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[2]))

from astrbot.api.star import StarTools  # noqa: E402
from astrbot.core.message.components import Plain  # noqa: E402
from astrbot.core.pipeline.process_stage.method.star_request import StarRequestSubStage  # noqa: E402
from astrbot.core.platform.astr_message_event import AstrMessageEvent  # noqa: E402
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember  # noqa: E402
from astrbot.core.platform.message_type import MessageType  # noqa: E402
from astrbot.core.platform.platform_metadata import PlatformMetadata  # noqa: E402
from astrbot.core.star.star import StarMetadata, star_map  # noqa: E402
from astrbot.core.star.star_handler import EventType, StarHandlerMetadata  # noqa: E402
from astrbot_plugin_anime_party_33989.main import AnimePartyPlugin  # noqa: E402
from astrbot_plugin_anime_party_33989.game.models import Question, Difficulty  # noqa: E402


def event(text, mid):
    message = AstrBotMessage()
    message.type = MessageType.GROUP_MESSAGE
    message.self_id = "test-bot"
    message.message_id = mid
    message.sender = MessageMember("test-user", "Tester")
    message.message = [Plain(text)]
    message.message_str = text
    message.raw_message = {}
    message.group_id = "test-group"
    e = AstrMessageEvent(text, message, PlatformMetadata("aiocqhttp", "test", "test-platform"), "test-group")
    e.role = "admin"
    e.send = AsyncMock()
    return e


async def main():
    question = Question(
        1,
        "测试动画",
        ("测试别名",),
        "😀 😀 😀 😀 😀\n😀 😀 😀 😀 😀 😀 😀\n😀 😀 😀 😀 😀",
        Difficulty.NORMAL,
        ("甲", "乙", "丙"),
        "测试",
    )
    with (
        tempfile.TemporaryDirectory() as td,
        patch.object(StarTools, "get_data_dir", return_value=Path(td)),
        patch("astrbot_plugin_anime_party_33989.main.generate_question", AsyncMock(return_value=question)),
    ):
        e = event("猜动画 开始", "m1")
        plugin = AnimePartyPlugin(
            SimpleNamespace(get_current_chat_provider_id=AsyncMock(return_value="test")),
            {"allowed_sessions": [e.unified_msg_origin]},
        )
        reached = []

        async def later(e):
            reached.append(True)

        star_map["test_later"] = StarMetadata(name="test-later")
        first = StarHandlerMetadata(
            event_type=EventType.AdapterMessageEvent,
            handler_full_name="test-game",
            handler_module_path=plugin.__class__.__module__,
            handler_name="on_message",
            handler=plugin.on_message,
            event_filters=[],
        )
        second = StarHandlerMetadata(
            event_type=EventType.AdapterMessageEvent,
            handler_full_name="test-later",
            handler_module_path="test_later",
            handler_name="later",
            handler=later,
            event_filters=[],
        )
        stage = StarRequestSubStage()
        await stage.initialize(
            SimpleNamespace(astrbot_config={"provider_settings": {"prompt_prefix": "", "identifier": ""}})
        )
        e.set_extra("activated_handlers", [first, second])
        e.set_extra("handlers_parsed_params", {})
        count = 0
        async for _ in stage.process(e):
            if e.get_result() and any("猜猜这部动画" in getattr(x, "text", "") for x in e.get_result().chain):
                count += 1
                assert any("猜猜这部动画" in getattr(x, "text", "") for x in e.get_result().chain)
        assert count == 1 and e.is_stopped() and not reached
        plain = event("今天大家晚上吃什么呀", "m2")
        plain.set_extra("activated_handlers", [first, second])
        plain.set_extra("handlers_parsed_params", {})
        async for _ in stage.process(plain):
            pass
        assert reached and not plain.is_stopped()
        reached.clear()
        hint = event("提示", "m3")
        hint.set_extra("activated_handlers", [first, second])
        hint.set_extra("handlers_parsed_params", {})
        hint_count = 0
        async for _ in stage.process(hint):
            if hint.get_result():
                hint_count += 1
                assert any("提示 1/3" in getattr(x, "text", "") for x in hint.get_result().chain)
        assert hint_count == 1 and hint.is_stopped() and not reached
        print(
            "REAL AstrBot events + processing stage: one game reply, later handler blocked, ordinary chat passes: PASS"
        )


if __name__ == "__main__":
    asyncio.run(main())
