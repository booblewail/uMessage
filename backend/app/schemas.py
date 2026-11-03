"""API request/response models: snake_case in Python, camelCase in JSON."""

import re
from collections.abc import Sequence
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    WithJsonSchema,
    field_validator,
)
from pydantic.alias_generators import to_camel

from app.adapters.protocols import ChatKind, Platform
from app.first_import import FirstImportState
from app.inbox import ChatSummary
from app.models import Chat, DetectedEvent, DetectedEventStatus, Message


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class HealthOut(ApiModel):
    status: Literal["ok"]
    database: Literal["ok"]


class MessageSourceStatusOut(ApiModel):
    name: str
    running: bool


class FirstImportOut(ApiModel):
    state: FirstImportState
    chats_total: int | None = Field(description="Known once the Chats have been listed")
    chats_imported: int
    error: str | None


class PlanDetectionOut(ApiModel):
    enabled: bool = Field(description="Whether new Messages are checked for plans")
    reason: str | None = Field(description="Why plan detection is off (null when it is on)")
    last_error: str | None = Field(
        description="Why the last Plan Model call failed; null once one succeeds"
    )


class CalendarStatusOut(ApiModel):
    connected: bool = Field(description="Whether Calendar Entries can be created right now")
    reason: str | None = Field(description="Why not, and what to do (null when connected)")


class StatusOut(ApiModel):
    mode: Literal["real", "demo"]
    message_source: MessageSourceStatusOut
    first_import: FirstImportOut
    plan_detection: PlanDetectionOut
    calendar: CalendarStatusOut


class LastMessageOut(ApiModel):
    sender_name: str
    text: str
    sent_at: datetime
    outbound: bool


class ChatOut(ApiModel):
    id: int
    platform: Platform
    kind: Literal["one_to_one", "group"]
    title: str
    last_message_at: datetime = Field(
        description="When the last Message was sent (the Chat's last activity if it has none)"
    )
    last_message: LastMessageOut | None
    excluded: bool = Field(description="An Excluded Chat: never checked for plans")


class ChatUpdateIn(ApiModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    excluded: bool = Field(description="True makes it an Excluded Chat; false includes it again")


class ChatsOut(ApiModel):
    chats: list[ChatOut] = Field(description="Newest first, by `lastMessageAt`")


class EventChatOut(ApiModel):
    """The Chat a Detected Event was found in, as a review card names it."""

    id: int
    title: str
    platform: Platform


class AnchorMessageOut(ApiModel):
    """A Detected Event's Anchor Message, as a review card quotes it."""

    id: int
    sender_name: str
    text: str
    sent_at: datetime
    outbound: bool


class CalendarEntryRefOut(ApiModel):
    """An upcoming Calendar Entry: the Confirmed Detected Event it was made from."""

    id: int = Field(description="The Confirmed Detected Event's id")
    title: str
    start: datetime
    all_day: bool


class DetectedEventOut(ApiModel):
    id: int
    chat_id: int
    chat: EventChatOut
    anchor_message_id: int = Field(description="The Message the inbox shows it beneath")
    anchor_message: AnchorMessageOut = Field(
        description="Its Anchor Message; link to it as /inbox?chat=<chatId>&message=<id>"
    )
    title: str
    start: datetime = Field(description="UTC; an all-day plan starts at local midnight")
    end: datetime | None = Field(
        description="UTC; null when the Chat didn't say. All-day: midnight of its last day"
    )
    all_day: bool
    location: str | None
    confidence: float = Field(description="How sure the Plan Model was, 0-1")
    status: DetectedEventStatus = Field(
        description="`confirming` only while its Calendar Entry is being created"
    )
    calendar_entry_id: str | None = Field(description="Its Calendar Entry, once Confirmed")
    existing_calendar_entries: list[CalendarEntryRefOut] = Field(
        description="The upcoming Calendar Entries its Chat already has (other Confirmed "
        "Detected Events of the Chat whose start, or all-day last day, isn't past), soonest "
        "first: 'You already have ... from this Chat'"
    )
    created_at: datetime
    updated_at: datetime


_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _date_or_datetime(value: object) -> object:
    """ "2026-11-06" is a date; anything longer an ISO 8601 date and time."""
    if not isinstance(value, str):
        return value
    try:
        if _DATE_ONLY.fullmatch(value):
            return date.fromisoformat(value)
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{value!r} is neither YYYY-MM-DD nor an ISO 8601 date and time") from exc


DateOrDateTime = Annotated[
    datetime | date,
    BeforeValidator(_date_or_datetime),
    WithJsonSchema({"type": "string", "description": "YYYY-MM-DD, or ISO 8601 with offset"}),
]


class ConfirmIn(ApiModel):
    """Edits to make before confirming; whatever is left out stays as detected."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    title: str | None = None
    start: DateOrDateTime | None = Field(
        default=None,
        description="Timed: an ISO 8601 date and time with offset. All-day: YYYY-MM-DD, "
        "its first day. Required when `allDay` changes",
    )
    end: DateOrDateTime | None = Field(
        default=None,
        description="Like `start`; all-day: its last day (inclusive). null: no end (a timed "
        "plan gets the default length; an all-day one is a single day)",
    )
    all_day: bool | None = None
    location: str | None = Field(default=None, description="Blank or null: no location")

    @field_validator("title")
    @classmethod
    def _has_title(cls, value: str | None) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("the title can't be empty")
        return value

    @field_validator("all_day")
    @classmethod
    def _not_null(cls, value: bool | None) -> bool:
        if value is None:
            raise ValueError("allDay is true or false")
        return value

    @field_validator("location")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class DetectedEventsOut(ApiModel):
    events: list[DetectedEventOut] = Field(description="Soonest first, by `start`")


class MessageOut(ApiModel):
    id: int
    chat_id: int
    sender_name: str
    sent_at: datetime
    text: str
    outbound: bool = Field(description="True for an Outbound Message (sent by the user)")
    detected_events: list[DetectedEventOut] = Field(
        description="The Detected Events (any status) it is the Anchor Message of; "
        "usually none or one"
    )


class ReplyIn(ApiModel):
    text: str = Field(description="The Message to send; surrounding whitespace is dropped")

    @field_validator("text")
    @classmethod
    def _has_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("a Message needs some text")
        return value


class MessagePageOut(ApiModel):
    messages: list[MessageOut] = Field(
        description="Oldest first: the newest `limit` older than `before`, the oldest `limit` "
        "newer than `after`, or `limit` with `around` in the middle"
    )
    has_older: bool = Field(
        description="Whether the Chat has older Messages (stored, or still in Beeper Desktop)"
    )
    older_cursor: int | None = Field(
        description="Pass as `before` to get the page of older Messages; null if none"
    )
    has_newer: bool = Field(
        description="Whether the Chat has newer Messages than these (false: up to the present)"
    )
    newer_cursor: int | None = Field(
        description="Pass as `after` to get the page of newer Messages; null if none"
    )


class ConnectedEvent(ApiModel):
    """Sent once when `/ws` connects; the inbox refetches then, to catch up on anything missed."""

    type: Literal["CONNECTED"] = "CONNECTED"


class NewMessageEvent(ApiModel):
    """A Message was just stored: `message` as the messages API shows it, and its Chat as the
    Chats API now lists it (it moves to the top; a new Chat is added)."""

    type: Literal["NEW_MESSAGE"] = "NEW_MESSAGE"
    chat_id: int
    message: MessageOut
    chat: ChatOut


class EventDetectedEvent(ApiModel):
    """A Detected Event was created, or changed (revised by plan detection, re-anchored,
    Confirmed or Dismissed): `event` as the events API now shows it."""

    type: Literal["EVENT_DETECTED"] = "EVENT_DETECTED"
    change: Literal["created", "updated"]
    event: DetectedEventOut


def detected_event_out(
    event: DetectedEvent,
    chat: Chat,
    anchor: Message,
    existing_calendar_entries: Sequence[DetectedEvent] = (),
) -> DetectedEventOut:
    return DetectedEventOut(
        id=event.id,
        chat_id=event.chat_id,
        chat=EventChatOut(id=chat.id, title=chat.title, platform=chat.platform),
        anchor_message_id=event.anchor_message_id,
        anchor_message=AnchorMessageOut(
            id=anchor.id,
            sender_name=anchor.sender_name,
            text=anchor.text,
            sent_at=anchor.sent_at,
            outbound=anchor.outbound,
        ),
        title=event.title,
        start=event.start_at,
        end=event.end_at,
        all_day=event.all_day,
        location=event.location,
        confidence=event.confidence,
        status=event.status,
        calendar_entry_id=event.calendar_entry_id,
        existing_calendar_entries=[
            CalendarEntryRefOut(
                id=other.id, title=other.title, start=other.start_at, all_day=other.all_day
            )
            for other in existing_calendar_entries
            if other.id != event.id
        ],
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def message_out(message: Message, detected_events: Sequence[DetectedEventOut] = ()) -> MessageOut:
    return MessageOut(
        id=message.id,
        chat_id=message.chat_id,
        sender_name=message.sender_name,
        sent_at=message.sent_at,
        text=message.text,
        outbound=message.outbound,
        detected_events=list(detected_events),
    )


def chat_out(summary: ChatSummary) -> ChatOut:
    chat, last = summary.chat, summary.last_message
    return ChatOut(
        id=chat.id,
        platform=chat.platform,
        kind="group" if chat.kind is ChatKind.GROUP else "one_to_one",
        title=chat.title,
        excluded=chat.excluded,
        last_message_at=summary.last_message_at,
        last_message=None
        if last is None
        else LastMessageOut(
            sender_name=last.sender_name,
            text=last.text,
            sent_at=last.sent_at,
            outbound=last.outbound,
        ),
    )
