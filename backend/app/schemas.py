"""API request/response models: snake_case in Python, camelCase in JSON."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from app.adapters.protocols import ChatKind, Platform
from app.first_import import FirstImportState
from app.inbox import ChatSummary
from app.models import Message


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


class StatusOut(ApiModel):
    mode: Literal["real", "demo"]
    message_source: MessageSourceStatusOut
    first_import: FirstImportOut


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


class ChatsOut(ApiModel):
    chats: list[ChatOut] = Field(description="Newest first, by `lastMessageAt`")


class MessageOut(ApiModel):
    id: int
    chat_id: int
    sender_name: str
    sent_at: datetime
    text: str
    outbound: bool = Field(description="True for an Outbound Message (sent by the user)")


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


def message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        chat_id=message.chat_id,
        sender_name=message.sender_name,
        sent_at=message.sent_at,
        text=message.text,
        outbound=message.outbound,
    )


def chat_out(summary: ChatSummary) -> ChatOut:
    chat, last = summary.chat, summary.last_message
    return ChatOut(
        id=chat.id,
        platform=chat.platform,
        kind="group" if chat.kind is ChatKind.GROUP else "one_to_one",
        title=chat.title,
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
