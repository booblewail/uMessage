"""API request/response models: snake_case in Python, camelCase in JSON."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.adapters.protocols import Platform
from app.first_import import FirstImportState


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


class MessagePageOut(ApiModel):
    messages: list[MessageOut] = Field(
        description="The newest `limit` Messages older than `before`, oldest first"
    )
    has_older: bool = Field(description="Whether older Messages are stored")
    older_cursor: int | None = Field(
        description="Pass as `before` to get the page of older Messages; null if none"
    )
