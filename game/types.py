"""Minimal contracts extracted from Apeiria; no runtime dependency on it."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    message_id: str
    session_id: str
    sender_id: str
    text: str


class StateStore(Protocol):
    def get(self, namespace: str, key: str) -> str | None: ...
    def set(self, namespace: str, key: str, value: str) -> None: ...
