"""In-memory adapters for tests and demo mode; tests steer them through their attributes."""

import asyncio
from collections.abc import Iterable, Sequence
from datetime import datetime

from app.adapters.protocols import (
    BEEPER_DESKTOP,
    MessageSourceStatus,
    MessageSourceUnavailableError,
    SourceChat,
    SourceMessage,
)


class FakeMessageSourceError(RuntimeError):
    """What the fake raises for a Chat listed in `failing_chats`."""


class FakeMessageSource:
    """Stands in for Beeper Desktop.

    Steer it through its attributes: `running` (Beeper Desktop open or closed), `chats` and
    `messages` (what Beeper Desktop holds, by Chat source id), `failing_chats` (source
    ids of Chats whose Messages can't be read right now) and `messages_readable` (clear it
    to make reading Messages wait until it is set again).
    """

    def __init__(self, *, running: bool = True) -> None:
        self.running = running
        self.chats: list[SourceChat] = []
        self.messages: dict[str, list[SourceMessage]] = {}
        self.failing_chats: set[str] = set()
        self.messages_readable = asyncio.Event()
        self.messages_readable.set()

    def add_chat(self, chat: SourceChat, messages: Iterable[SourceMessage] = ()) -> None:
        self.chats.append(chat)
        self.messages.setdefault(chat.source_id, []).extend(messages)

    async def status(self) -> MessageSourceStatus:
        return MessageSourceStatus(name=BEEPER_DESKTOP, running=self.running)

    async def list_chats(self, *, active_since: datetime) -> Sequence[SourceChat]:
        self._require_running()
        return [chat for chat in self.chats if chat.last_activity >= active_since]

    async def recent_messages(self, chat_source_id: str, *, limit: int) -> Sequence[SourceMessage]:
        await self.messages_readable.wait()
        self._require_running()
        if chat_source_id in self.failing_chats:
            raise FakeMessageSourceError(f"can't read the Messages of {chat_source_id}")
        messages = sorted(self.messages.get(chat_source_id, []), key=lambda m: m.sent_at)
        return messages[-limit:] if limit > 0 else []

    def _require_running(self) -> None:
        if not self.running:
            raise MessageSourceUnavailableError(f"{BEEPER_DESKTOP} isn't running")


class FakePlanModel:
    """Stands in for Gemini."""


class FakeCalendar:
    """Stands in for Google Calendar."""
