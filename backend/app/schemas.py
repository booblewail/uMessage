"""API request/response models: snake_case in Python, camelCase in JSON."""

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from app.adapters.protocols import ChatKind, Platform
from app.first_import import FirstImportState
from app.inbox import ChatSummary
from app.models import DetectedEvent, DetectedEventStatus, Message


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


class StatusOut(ApiModel):
    mode: Literal["real", "demo"]
    message_source: MessageSourceStatusOut
    first_import: FirstImportOut
    plan_detection: PlanDetectionOut


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


class DetectedEventOut(ApiModel):
    id: int
    chat_id: int
    anchor_message_id: int = Field(description="The Message the inbox shows it beneath")
    title: str
    start: datetime = Field(description="UTC; an all-day plan starts at local midnight")
    end: datetime | None = Field(
        description="UTC; null when the Chat didn't say. All-day: midnight of its last day"
    )
    all_day: bool
    location: str | None
    confidence: float = Field(description="How sure the Plan Model was, 0-1")
    status: DetectedEventStatus
    created_at: datetime
    updated_at: datetime


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
        description="The newest `limit` Messages older than `before`, oldest first"
    )
    has_older: bool = Field(
        description="Whether the Chat has older Messages (stored, or still in Beeper Desktop)"
    )
    older_cursor: int | None = Field(
        description="Pass as `before` to get the page of older Messages; null if none"
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
    """A Detected Event was created, or changed (revised by plan detection, re-anchored, or
    Dismissed): `event` as the events API now shows it."""

    type: Literal["EVENT_DETECTED"] = "EVENT_DETECTED"
    change: Literal["created", "updated"]
    event: DetectedEventOut


def detected_event_out(event: DetectedEvent) -> DetectedEventOut:
    return DetectedEventOut(
        id=event.id,
        chat_id=event.chat_id,
        anchor_message_id=event.anchor_message_id,
        title=event.title,
        start=event.start_at,
        end=event.end_at,
        all_day=event.all_day,
        location=event.location,
        confidence=event.confidence,
        status=event.status,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def message_out(message: Message, detected_events: Sequence[DetectedEvent] = ()) -> MessageOut:
    return MessageOut(
        id=message.id,
        chat_id=message.chat_id,
        sender_name=message.sender_name,
        sent_at=message.sent_at,
        text=message.text,
        outbound=message.outbound,
        detected_events=[detected_event_out(event) for event in detected_events],
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
