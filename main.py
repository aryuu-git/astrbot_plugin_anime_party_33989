"""AstrBot adapter. Game outcomes remain independent of model output."""

import asyncio
import json
import uuid

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools, register

from .game.catalog import QuestionCatalog, default_questions_path, load_questions
from .game.expression import expression_payload, valid_lead
from .game.service import GameService

PLUGIN_ID = "astrbot_plugin_anime_party_33989"


@register(PLUGIN_ID, "aryuu-git", "Emoji 猜动画：确定性判题、分层提示、可选AI主持", "0.1.2")
class AnimePartyPlugin(Star):
    def __init__(self, context: Context, config):
        super().__init__(context)
        self.config = config
        self.data_dir = StarTools.get_data_dir(PLUGIN_ID)
        self._locks = {}
        self._timer = None
        self.service = self._build_service()

    def _build_service(self):
        source = self.config.get("question_source", "builtin")
        builtin = load_questions(default_questions_path())
        if source == "builtin":
            catalog = builtin
        else:
            custom = load_questions(self.data_dir / "custom_questions.json")
            if source == "custom":
                catalog = custom
            elif source == "merged":
                combined = {q.subject_id: q for q in builtin.questions}
                combined.update({q.subject_id: q for q in custom.questions})
                catalog = QuestionCatalog(combined.values())
            else:
                raise ValueError("question_source 必须为 builtin/custom/merged")
        return GameService(
            self.data_dir / "game.db",
            catalog,
            timeout=float(self.config.get("round_timeout_minutes", 15)) * 60,
            recent_limit=int(self.config.get("recent_question_limit", 8)),
            plain_answers=bool(self.config.get("allow_known_title_answers", True)),
            shortcuts=bool(self.config.get("enable_shortcuts", True)),
        )

    def _allowed(self, session):
        return bool(self.config.get("enabled", True)) and session in self.config.get("allowed_sessions", [])

    def _lock(self, session):
        return self._locks.setdefault(session, asyncio.Lock())

    async def initialize(self):
        if self.service.timeout > 0:
            self._timer = asyncio.create_task(self._expire_loop())
        logger.info(
            "动画派对已就绪：%d道题，%d个允许会话。",
            self.service.catalog.size,
            len(self.config.get("allowed_sessions", [])),
        )

    async def terminate(self):
        if self._timer:
            self._timer.cancel()
            try:
                await self._timer
            except asyncio.CancelledError:
                pass

    @filter.event_message_type(filter.EventMessageType.ALL, priority=100)
    async def on_message(self, event: AstrMessageEvent):
        session = str(event.unified_msg_origin)
        if not self._allowed(session) or str(event.get_sender_id()) == str(event.get_self_id()):
            return
        # A message explicitly directed to somebody else belongs to their conversation.
        for segment in event.get_messages():
            if type(segment).__name__ in ("At", "Reply"):
                target = (
                    getattr(segment, "qq", None)
                    if type(segment).__name__ == "At"
                    else getattr(segment, "sender_id", None)
                )
                if str(target) != str(event.get_self_id()):
                    return
        text = event.message_str.strip()
        if not text or len(text) > 512:
            return
        message_id = str(event.message_obj.message_id or uuid.uuid4())
        async with self._lock(session):
            result = await asyncio.to_thread(
                self.service.handle,
                session,
                message_id,
                str(event.get_sender_id()),
                text,
                admin=event.is_admin(),
            )
            if not result.consumed:
                return
            # Consume before awaiting the model so later chat handlers cannot answer too.
            event.set_extra("anime_party_consumed", True)
            event.stop_event()
            if result.duplicate or not result.messages:
                return
            messages = result.messages
            if result.reply and self.config.get("ai_expression", False):
                lead = await self._lead(event, result.reply)
                if lead:
                    messages = (lead + "\n" + "\n".join(messages),)
            yield event.plain_result("\n".join(messages))

    async def _persona(self, event):
        umo = str(event.unified_msg_origin)
        manager = self.context.conversation_manager
        cid = await manager.get_curr_conversation_id(umo)
        conv = await manager.get_conversation(umo, cid) if cid else None
        _, persona, _, _ = await self.context.persona_manager.resolve_selected_persona(
            umo=umo,
            conversation_persona_id=getattr(conv, "persona_id", None),
            platform_name=event.get_platform_name(),
            provider_settings=self.context.get_config(umo).get("provider_settings", {}),
        )
        return persona.get("prompt", "") if persona else ""

    async def _lead(self, event, reply):
        try:
            return await asyncio.wait_for(
                self._generate_lead(event, reply), timeout=float(self.config.get("ai_timeout_seconds", 10))
            )
        except Exception as exc:
            logger.debug("动画派对AI表达回退模板：%s", type(exc).__name__)
            return ""

    async def _generate_lead(self, event, reply):
        provider_id = self.config.get("provider_id", "") or await self.context.get_current_chat_provider_id(
            event.unified_msg_origin
        )
        persona = await self._persona(event)
        response = await self.context.llm_generate(
            chat_provider_id=provider_id,
            system_prompt=persona
            + "\n你在和熟人玩Emoji猜动画。可返回空字符串；若确实需要接话，只写一句不超过12字的自然短句。不要自报姓名、撒娇、说自己期待大家推理，也不要每次重复宣布新题开始。不要写题目、作品名、角色、线索、判题结论或规则。固定游戏信息由程序附加，禁止索要或猜测隐藏答案。",
            prompt=json.dumps(expression_payload(reply), ensure_ascii=False),
        )
        lead = response.completion_text.strip()
        return lead if valid_lead(lead, reply) else ""

    async def _expire_loop(self):
        while True:
            await asyncio.sleep(30)
            try:
                for session in await asyncio.to_thread(self.service.sessions):
                    if not self._allowed(session):
                        continue
                    async with self._lock(session):
                        result = await asyncio.to_thread(self.service.expire, session)
                        if result.messages:
                            delivered = await self.context.send_message(
                                session, MessageChain().message("\n".join(result.messages))
                            )
                            if not delivered:
                                logger.warning("动画派对超时揭晓未找到投递平台。")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("动画派对超时检查失败：%s", type(exc).__name__)
