"""Interfaces the backend core uses to reach the outside world.

The Message Source speaks in plain DTOs (`SourceChat`, `SourceMessage`) that each adapter
maps its own data onto: the core never sees Beeper's networks, chat types or message types.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

BEEPER_DESKTOP = "Beeper Desktop"


class Platform(StrEnum):
    """The messaging services uMessage supports. Chats on anything else are skipped."""

    IMESSAGE = "imessage"
    INSTAGRAM = "instagram"
    MESSENGER = "messenger"
    WHATSAPP = "whatsapp"
    DISCORD = "discord"


class ChatKind(StrEnum):
    """What a Message Source conversation is, normalised across Platforms.

    `SERVER_CHANNEL` (a Discord server channel) is not a Chat: the core never stores one.
    """

    ONE_TO_ONE = "one_to_one"
    GROUP = "group"
    SERVER_CHANNEL = "server_channel"


class MessageSourceUnavailableError(Exception):
    """The Message Source can't be reached (e.g. Beeper Desktop isn't running)."""


@dataclass(frozen=True, slots=True)
class MessageSourceStatus:
    """Whether the Message Source (Beeper Desktop) can be reached right now."""

    name: str
    running: bool


@dataclass(frozen=True, slots=True)
class SourceChat:
    """A conversation as the Message Source reports it.

    `source_id` is the Message Source's own, stable id for it; `last_activity` is
    timezone-aware.
    """

    source_id: str
    platform: Platform
    kind: ChatKind
    title: str
    last_activity: datetime


@dataclass(frozen=True, slots=True)
class SourceMessage:
    """A text Message as the Message Source reports it.

    `source_id` is the Message Source's id for it, unique within its Chat. The adapter
    supplies `sender_name` (resolving it from the Chat's participants if it must) and sets
    `outbound` for Messages the user sent from any client. `sent_at` is timezone-aware.
    `paging_key` is the Message Source's own, opaque position for the Message (Beeper's
    `sortKey`), if it pages by one: the core stores it and hands it back in `older_messages`.
    """

    source_id: str
    sender_name: str
    sent_at: datetime
    text: str
    outbound: bool
    paging_key: str | None = None


@dataclass(frozen=True, slots=True)
class SourceMessageRef:
    """Points at a Message the core has: its `source_id` and `paging_key` as reported."""

    source_id: str
    paging_key: str | None


@dataclass(frozen=True, slots=True)
class OlderMessages:
    """What `MessageSource.older_messages` found: up to `limit` Messages, in any order, and
    whether the Chat has any older still (False: this is the start of its history)."""

    messages: Sequence[SourceMessage]
    has_more: bool


@dataclass(frozen=True, slots=True)
class NewMessages:
    """What `MessageSource.new_messages` found: Messages that arrived after a cursor.

    `messages` pairs each Message with its Chat (as it is now), in the order they arrived.
    `cursor` is opaque to the core: it is stored and handed back as `since` next time, so it
    must survive a restart. Fetching again from an older cursor may repeat Messages; the
    core stores each Message once.
    """

    messages: Sequence[tuple[SourceChat, SourceMessage]]
    cursor: str


@dataclass(frozen=True, slots=True)
class SentMessage:
    """A Message the Message Source accepted for sending.

    `source_id` may be provisional (Beeper's `pendingMessageID`): the same Message can come
    back through `new_messages` under a different, final id. `sent_at` is timezone-aware.
    """

    source_id: str
    sent_at: datetime


class MessageSource(Protocol):
    """Where Chats and Messages come from and where Outbound Messages go (Beeper Desktop).

    Any operation may raise `MessageSourceUnavailableError` while it can't be reached.
    """

    async def status(self) -> MessageSourceStatus: ...

    async def list_chats(self, *, active_since: datetime) -> Sequence[SourceChat]:
        """Every conversation on a supported Platform with activity at or after
        `active_since`, of any `ChatKind` (the core drops server channels)."""
        ...

    async def recent_messages(self, chat_source_id: str, *, limit: int) -> Sequence[SourceMessage]:
        """The newest `limit` text Messages of a Chat, in any order.

        Non-text items (media without text, reactions, state events) are left out.
        """
        ...

    async def new_messages(self, *, since: str | None) -> NewMessages:
        """Text Messages in any Chat (of any `ChatKind`) that arrived after cursor `since`.

        `since=None` starts from now: no Messages, just a cursor for the present.
        """
        ...

    async def older_messages(
        self, chat_source_id: str, *, before: SourceMessageRef | None, limit: int
    ) -> OlderMessages:
        """The (up to) `limit` text Messages of a Chat just older than Message `before`
        (the newest ones when None), going back through its full history."""
        ...

    async def send_message(self, chat_source_id: str, text: str) -> SentMessage:
        """Send a text Message to a Chat; raises if the Message Source didn't accept it.

        The sent Message is later reported by `new_messages` too, as an outbound Message.
        """
        ...


class PlanModel(Protocol):
    """Turns a window of Messages into a decision about a Detected Event (Gemini).

    Its operations arrive with the Detected Event tickets.
    """


class Calendar(Protocol):
    """Creates Calendar Entries for Confirmed Detected Events (Google Calendar).

    Its operations arrive with the Calendar Entry tickets.
    """
