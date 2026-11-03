"""Interfaces the backend core uses to reach the outside world.

The Message Source speaks in plain DTOs (`SourceChat`, `SourceMessage`) that each adapter
maps its own data onto: the core never sees Beeper's networks, chat types or message types.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
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


@dataclass(frozen=True, slots=True)
class PlanWindowMessage:
    """One Message of the window the Plan Model reads. `sent_at` is timezone-aware."""

    sender_name: str
    text: str
    sent_at: datetime
    outbound: bool


@dataclass(frozen=True, slots=True)
class PendingPlan:
    """A Pending Review Detected Event of the Chat, which the Plan Model may update by `id`.

    Times are timezone-aware (UTC); an all-day plan starts at local midnight of its date.
    """

    id: int
    title: str
    start: datetime
    end: datetime | None
    all_day: bool
    location: str | None


@dataclass(frozen=True, slots=True)
class PlanRequest:
    """What the Plan Model is asked about one Chat.

    `messages` are the Chat's latest Messages, oldest first; `pending` its Pending Review
    Detected Events; `timezone` the user's IANA time zone, in which relative dates ("Friday",
    "tomorrow at 7") are resolved against each Message's own `sent_at`; `now` is aware.
    """

    messages: Sequence[PlanWindowMessage]
    pending: Sequence[PendingPlan]
    timezone: str
    now: datetime


@dataclass(frozen=True, slots=True)
class PlanDetails:
    """A plan as the Plan Model describes it.

    `start` and `end` are either naive local wall times in the user's time zone or
    offset-aware; the core resolves them and stores UTC. For an all-day plan only the
    (local) date of `start`/`end` counts. `end` is None when the Chat didn't say.
    `confidence` is 0-1: how sure the model is that this is a plan the user will attend.
    """

    title: str
    start: datetime
    end: datetime | None
    all_day: bool
    location: str | None
    confidence: float


@dataclass(frozen=True, slots=True)
class NoPlan:
    """No new plan, and no change to a pending one."""


@dataclass(frozen=True, slots=True)
class NewPlan:
    """A plan that isn't one of the pending ones: it becomes a new Detected Event."""

    plan: PlanDetails


@dataclass(frozen=True, slots=True)
class UpdatePlan:
    """A change to pending Detected Event `event_id` (e.g. a new time): `plan` replaces it."""

    event_id: int
    plan: PlanDetails


PlanDecision = NoPlan | NewPlan | UpdatePlan


class PlanModel(Protocol):
    """Decides, from a Chat's latest Messages, whether they make or change a plan (Gemini).

    It is only ever sent Messages of Chats that aren't Excluded Chats (ADR-0005). It may
    raise anything on failure; the core logs it and carries on.
    """

    async def decide(self, request: PlanRequest) -> PlanDecision: ...


class CalendarUnavailableError(Exception):
    """The Calendar isn't connected (e.g. nobody has signed in to Google yet): its message
    says what the user should do."""


@dataclass(frozen=True, slots=True)
class CalendarStatus:
    """Whether Calendar Entries can be created right now, and if not, why (`reason`)."""

    connected: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class CalendarEntryRequest:
    """A Calendar Entry to create.

    Timed: `start` and `end` are aware datetimes, `end` after `start`. All-day: they are
    dates (no time), the first and the LAST day of the plan, both inclusive (`end == start`
    for a single day). `timezone` is the user's IANA time zone, which timed entries are shown
    in. `description` quotes the Chat the plan was made in. `entry_key` is stable for the
    Detected Event (and unique to this uMessage database): the Calendar makes at most one
    Calendar Entry per key.
    """

    title: str
    start: datetime | date
    end: datetime | date
    timezone: str
    location: str | None
    description: str
    entry_key: str

    def __post_init__(self) -> None:
        if self.all_day:
            if isinstance(self.end, datetime) or self.end < self.start:
                raise ValueError("an all-day Calendar Entry needs an end date on or after start")
        elif not (
            isinstance(self.start, datetime)
            and isinstance(self.end, datetime)
            and self.start.tzinfo is not None
            and self.end.tzinfo is not None
            and self.end > self.start
        ):
            raise ValueError("a timed Calendar Entry needs aware start and end, end after start")

    @property
    def all_day(self) -> bool:
        return not isinstance(self.start, datetime)  # a datetime is also a date


class Calendar(Protocol):
    """Creates Calendar Entries for Confirmed Detected Events (Google Calendar)."""

    async def status(self) -> CalendarStatus: ...

    async def create_entry(self, request: CalendarEntryRequest) -> str:
        """Create the Calendar Entry and return its id (unique across the Calendar).

        Idempotent by `request.entry_key`: if the Calendar Entry for that key already exists
        (it was created, but the app stopped before storing it), its id is returned and no
        second one is made. Raises `CalendarUnavailableError` while the Calendar isn't
        connected; anything else it raises means the Calendar Entry wasn't created.
        """
        ...
