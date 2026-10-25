"""Expose no question/answer/user text to the optional lead generator."""

from .models import normalize_answer


def expression_payload(reply):
    return {"event": reply.kind.value, "hint_level": reply.hint_level}


def valid_lead(text, reply):
    if not text or len(text) > 40 or "\n" in text or "\r" in text:
        return False
    if any(marker in text for marker in ("答案", "提示", "答对", "答错", "http", "<", "```")):
        return False
    if reply.question:
        normalized = normalize_answer(text)
        for name in (reply.question.title, *reply.question.aliases):
            value = normalize_answer(name)
            if value and value in normalized:
                return False
    return True
