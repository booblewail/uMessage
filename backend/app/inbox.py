"""Reading and writing the stored inbox: Chats and their Messages."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.protocols import Platform, SourceChat, SourceMessage
from app.models import Chat, Message


class NotFoundError(LookupError):
    """A Chat or Message cursor that isn't in the inbox."""


@dataclass(frozen=True, slots=True)
class ChatSummary:
    chat: Chat
    last_message: Message | None

    @property
    def last_message_at(self) -> datetime:
        """When the last Message was sent; a Chat without text Messages uses its last activity."""
        return self.last_message.sent_at if self.last_message else self.chat.last_activity_at


@dataclass(frozen=True, slots=True)
class MessagePage:
    messages: list[Message]  # oldest first
    has_older: bool


async def save_chat(
    session: AsyncSession, chat: SourceChat, messages: Sequence[SourceMessage]
) -> None:
    """Store a Chat and its Messages; a Chat or Message already stored is not duplicated."""
    upsert = insert(Chat).values(
        source_id=chat.source_id,
        platform=chat.platform,
        kind=chat.kind,
        title=chat.title,
        last_activity_at=chat.last_activity,
    )
    upsert = upsert.on_conflict_do_update(
        index_elements=[Chat.source_id],
        set_={
            "platform": upsert.excluded.platform,
            "kind": upsert.excluded.kind,
            "title": upsert.excluded.title,
            "last_activity_at": upsert.excluded.last_activity_at,
        },
    ).returning(Chat.id)
    chat_id = (await session.execute(upsert)).scalar_one()
    if not messages:
        return
    rows = [
        {
            "chat_id": chat_id,
            "source_id": message.source_id,
            "sender_name": message.sender_name,
            "sent_at": message.sent_at,
            "text": message.text,
            "outbound": message.outbound,
        }
        for message in messages
    ]
    await session.execute(
        insert(Message).values(rows).on_conflict_do_nothing(index_elements=["chat_id", "source_id"])
    )


async def list_chats(
    session: AsyncSession, *, platform: Platform | None = None
) -> list[ChatSummary]:
    """Every stored Chat, newest first by its last Message."""
    ranked = select(
        Message.id,
        Message.chat_id,
        func.row_number()
        .over(partition_by=Message.chat_id, order_by=(Message.sent_at.desc(), Message.id.desc()))
        .label("rank"),
    ).subquery()
    latest = select(ranked.c.id, ranked.c.chat_id).where(ranked.c.rank == 1).subquery()
    query = (
        select(Chat, Message)
        .outerjoin(latest, latest.c.chat_id == Chat.id)
        .outerjoin(Message, Message.id == latest.c.id)
        .order_by(func.coalesce(Message.sent_at, Chat.last_activity_at).desc(), Chat.id.desc())
    )
    if platform is not None:
        query = query.where(Chat.platform == platform)
    rows = (await session.execute(query)).all()
    return [ChatSummary(chat=chat, last_message=message) for chat, message in rows]


async def message_page(
    session: AsyncSession, chat_id: int, *, before: int | None, limit: int
) -> MessagePage:
    """The newest `limit` Messages of a Chat older than Message `before`, oldest first."""
    if await session.get(Chat, chat_id) is None:
        raise NotFoundError(f"no Chat {chat_id}")
    query = select(Message).where(Message.chat_id == chat_id)
    if before is not None:
        cursor = await session.get(Message, before)
        if cursor is None or cursor.chat_id != chat_id:
            raise NotFoundError(f"no Message {before} in Chat {chat_id}")
        query = query.where(
            or_(
                Message.sent_at < cursor.sent_at,
                and_(Message.sent_at == cursor.sent_at, Message.id < cursor.id),
            )
        )
    query = query.order_by(Message.sent_at.desc(), Message.id.desc()).limit(limit + 1)
    newest_first = list((await session.scalars(query)).all())
    return MessagePage(messages=newest_first[:limit][::-1], has_older=len(newest_first) > limit)
