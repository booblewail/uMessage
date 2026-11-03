"""In-memory adapters for tests and demo mode; tests steer them through their attributes."""

import asyncio
import dataclasses
import itertools
import uuid
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Literal

from app.adapters.protocols import (
    BEEPER_DESKTOP,
    MessageSourceStatus,
    MessageSourceUnavailableError,
    NewMessages,
    NoPlan,
    OlderMessages,
    PlanDecision,
    PlanRequest,
    SentMessage,
    SourceChat,
    SourceMessage,
    SourceMessageRef,
)

YOU = "You"


class FakeMessageSourceError(RuntimeError):
    """What the fake raises for a Chat listed in `failing_chats`."""


class FakeMessageSource:
    """Stands in for Beeper Desktop.

    Steer it through its attributes: `running` (Beeper Desktop open or closed), `chats` and
    `messages` (what Beeper Desktop holds, by Chat source id), `failing_chats` (source
    ids of Chats whose Messages can't be read right now) and `messages_readable` (clear it
    to make reading Messages wait until it is set again).

    Every Message added is also appended to an arrival log, which `new_messages` reads from:
    its cursor is the position in that log. A cursor from another fake (demo mode restarted
    with the database kept) starts from now, like a cursor Beeper no longer recognises.

    Sending: `sent` records what was sent, as (Chat source id, text); set `sending_fails` to
    make sending fail. Like Beeper, a sent Message is reported back by `new_messages`
    (`echo`): under the id it was sent with (`"same_id"`), under a different, final id
    (`"final_id"`, like Beeper's `pendingMessageID`), or not at all (None).
    """

    def __init__(self, *, running: bool = True) -> None:
        self.running = running
        self.chats: list[SourceChat] = []
        self.messages: dict[str, list[SourceMessage]] = {}
        self.failing_chats: set[str] = set()
        self.messages_readable = asyncio.Event()
        self.messages_readable.set()
        self._arrivals: list[tuple[str, SourceMessage]] = []
        self._log_id = uuid.uuid4().hex[:8]
        self.sent: list[tuple[str, str]] = []
        self.sending_fails = False
        self.echo: Literal["same_id", "final_id"] | None = "final_id"
        self._echoes: list[tuple[str, SourceMessage]] = []
        self._sent_numbers = itertools.count(1)

    def add_chat(self, chat: SourceChat, messages: Iterable[SourceMessage] = ()) -> None:
        self.chats.append(chat)
        self.messages.setdefault(chat.source_id, [])
        for message in messages:
            self._append(chat.source_id, message)

    def receive(self, chat_source_id: str, message: SourceMessage) -> None:
        """A Message arrives in a Chat Beeper Desktop already holds (the Chat moves up)."""
        self._append(chat_source_id, message)

    def redeliver_echoes(self) -> None:
        """Report every sent Message back once more (Beeper may report a Message again)."""
        for chat_source_id, message in self._echoes:
            self._arrivals.append((chat_source_id, message))

    def _append(self, chat_source_id: str, message: SourceMessage) -> None:
        self.messages.setdefault(chat_source_id, []).append(message)
        self._arrivals.append((chat_source_id, message))
        for index, chat in enumerate(self.chats):
            if chat.source_id == chat_source_id and message.sent_at > chat.last_activity:
                self.chats[index] = dataclasses.replace(chat, last_activity=message.sent_at)

    def _chat(self, chat_source_id: str) -> SourceChat:
        return next(chat for chat in self.chats if chat.source_id == chat_source_id)

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

    async def new_messages(self, *, since: str | None) -> NewMessages:
        self._require_running()
        log_id, _, position = (since or "").partition(":")
        start = int(position) if log_id == self._log_id else len(self._arrivals)
        arrived = self._arrivals[start:]
        return NewMessages(
            messages=[(self._chat(chat_id), message) for chat_id, message in arrived],
            cursor=f"{self._log_id}:{start + len(arrived)}",
        )

    async def older_messages(
        self, chat_source_id: str, *, before: SourceMessageRef | None, limit: int
    ) -> OlderMessages:
        """Pages back like Beeper: from `before`'s position, which a Message reported with a
        `paging_key` must be referred to by."""
        self._require_running()
        messages = sorted(self.messages.get(chat_source_id, []), key=lambda m: m.sent_at)
        end = len(messages)
        if before is not None:
            positions = [i for i, m in enumerate(messages) if m.source_id == before.source_id]
            if not positions:
                raise FakeMessageSourceError(f"no Message {before.source_id} to page back from")
            end = positions[0]
            if messages[end].paging_key not in (None, before.paging_key):
                raise FakeMessageSourceError(f"wrong paging key for {before.source_id}")
        start = max(end - limit, 0)
        return OlderMessages(messages=messages[start:end], has_more=start > 0)

    async def send_message(self, chat_source_id: str, text: str) -> SentMessage:
        self._require_running()
        if self.sending_fails:
            raise FakeMessageSourceError(f"can't send to {chat_source_id}")
        self._chat(chat_source_id)  # an unknown Chat is a bug in the test
        self.sent.append((chat_source_id, text))
        number = next(self._sent_numbers)
        sent = SentMessage(source_id=f"pending-{number}", sent_at=datetime.now(UTC))
        if self.echo is not None:
            echo = SourceMessage(
                source_id=sent.source_id if self.echo == "same_id" else f"sent-{number}",
                sender_name=YOU,
                sent_at=sent.sent_at,
                text=text,
                outbound=True,
            )
            self._echoes.append((chat_source_id, echo))
            self._append(chat_source_id, echo)
        return sent

    def _require_running(self) -> None:
        if not self.running:
            raise MessageSourceUnavailableError(f"{BEEPER_DESKTOP} isn't running")


PlanResponder = Callable[[PlanRequest], PlanDecision]


class FakePlanModel:
    """Stands in for Gemini.

    `calls` records every request, so tests can assert exactly what was sent. Each call takes
    the next scripted decision from `will_decide(...)`: a decision, an exception (raised), or
    a function of the request. With none scripted it asks `respond` (demo mode's rules), or
    decides `NoPlan`. Clear `answering` to hold calls until it is set again; `in_flight` and
    `most_in_flight` count calls being answered.
    """

    def __init__(self, respond: PlanResponder | None = None) -> None:
        self.calls: list[PlanRequest] = []
        self._script: deque[PlanDecision | Exception | PlanResponder] = deque()
        self._respond = respond
        self.answering = asyncio.Event()
        self.answering.set()
        self.in_flight = 0
        self.most_in_flight = 0

    def will_decide(self, *decisions: PlanDecision | Exception | PlanResponder) -> None:
        self._script.extend(decisions)

    async def decide(self, request: PlanRequest) -> PlanDecision:
        self.calls.append(request)
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        try:
            await self.answering.wait()
            if not self._script:
                return self._respond(request) if self._respond else NoPlan()
            decision = self._script.popleft()
            if isinstance(decision, Exception):
                raise decision
            if callable(decision):
                return decision(request)
            return decision
        finally:
            self.in_flight -= 1


class FakeCalendar:
    """Stands in for Google Calendar."""
