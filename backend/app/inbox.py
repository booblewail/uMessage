"""Reading and writing the stored inbox: Chats and their Messages."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.protocols import (
    MessageSource,
    OlderMessages,
    Platform,
    SentMessage,
    SourceChat,
    SourceMessage,
    SourceMessageRef,
)
from app.models import Chat, Message, NewMessagesCursor

# The sender name of Outbound Messages sent from uMessage.
YOU = "You"
# How far apart in time a pending Outbound Message and its report back may be.
ECHO_WINDOW = timedelta(minutes=10)


logger = logging.getLogger(__name__)


class NotFoundError(LookupError):
    """A Chat or Message cursor that isn't in the inbox."""


class OlderMessagesUnavailableError(Exception):
    """Older Messages are needed from the Message Source, which can't give them right now."""


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
    chat_id, excluded = await _save_chat_details(session, chat)
    if not messages:
        return
    await session.execute(
        insert(Message)
        .values([_message_row(chat_id, message, excluded) for message in messages])
        .on_conflict_do_nothing(index_elements=["chat_id", "source_id"])
    )


async def save_new_message(
    session: AsyncSession, chat: SourceChat, message: SourceMessage
) -> int | None:
    """Store a Message that just arrived (and its Chat, which may be new).

    Returns the stored Message's id, or None if it was already stored. That includes an
    Outbound Message sent from uMessage coming back from the Message Source, maybe under a
    different, final id: it is matched to the pending one (same Chat, same text, close in
    time; oldest first), which takes on the final id and time instead of being stored twice.
    """
    chat_id, excluded = await _save_chat_details(session, chat)
    stored = await session.scalar(
        select(Message).where(Message.chat_id == chat_id, Message.source_id == message.source_id)
    )
    if stored is None and message.outbound:
        stored = await _pending_match(session, chat_id, message)
    if stored is not None:
        if stored.pending:
            stored.source_id = message.source_id
            stored.sent_at = message.sent_at
            stored.paging_key = message.paging_key
            stored.pending = False
            await session.flush()
        return None
    inserted = await session.execute(
        insert(Message)
        .values(_message_row(chat_id, message, excluded))
        .on_conflict_do_nothing(index_elements=["chat_id", "source_id"])
        .returning(Message.id)
    )
    return inserted.scalar_one_or_none()


async def save_sent_message(
    session: AsyncSession, chat_id: int, sent: SentMessage, text: str
) -> Message:
    """Store a Message just sent from uMessage, pending until the Message Source reports it."""
    chat = await session.get_one(Chat, chat_id)
    message = Message(
        chat_id=chat_id,
        source_id=sent.source_id,
        sender_name=YOU,
        sent_at=sent.sent_at,
        text=text,
        outbound=True,
        pending=True,
        excluded_from_plans=chat.excluded,
    )
    session.add(message)
    await session.flush()
    return message


async def _pending_match(
    session: AsyncSession, chat_id: int, message: SourceMessage
) -> Message | None:
    return await session.scalar(
        select(Message)
        .where(
            Message.chat_id == chat_id,
            Message.pending,
            Message.text == message.text,
            Message.sent_at.between(message.sent_at - ECHO_WINDOW, message.sent_at + ECHO_WINDOW),
        )
        .order_by(Message.sent_at, Message.id)
        .limit(1)
    )


async def stored_cursor(session: AsyncSession) -> str | None:
    """Where fetching new Messages resumes; None before it has ever started."""
    record = await session.get(NewMessagesCursor, 1)
    return record.cursor if record else None


async def store_cursor(session: AsyncSession, cursor: str) -> None:
    upsert = insert(NewMessagesCursor).values(id=1, cursor=cursor, updated_at=datetime.now(UTC))
    await session.execute(
        upsert.on_conflict_do_update(
            index_elements=[NewMessagesCursor.id],
            set_={"cursor": upsert.excluded.cursor, "updated_at": upsert.excluded.updated_at},
        )
    )


def _message_row(chat_id: int, message: SourceMessage, chat_excluded: bool) -> dict[str, object]:
    """A Message stored while its Chat is an Excluded Chat is never sent to the Plan Model."""
    return {
        "chat_id": chat_id,
        "source_id": message.source_id,
        "sender_name": message.sender_name,
        "sent_at": message.sent_at,
        "text": message.text,
        "outbound": message.outbound,
        "paging_key": message.paging_key,
        "excluded_from_plans": chat_excluded,
    }


async def _save_chat_details(session: AsyncSession, chat: SourceChat) -> tuple[int, bool]:
    """Insert or update a Chat by its source id; returns its id and whether it is excluded."""
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
    ).returning(Chat.id, Chat.excluded)
    chat_id, excluded = (await session.execute(upsert)).one()
    return chat_id, excluded


async def list_chats(
    session: AsyncSession, *, platform: Platform | None = None, chat_id: int | None = None
) -> list[ChatSummary]:
    """Every stored Chat (or just Chat `chat_id`), newest first by its last Message."""
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
    if chat_id is not None:
        query = query.where(Chat.id == chat_id)
    rows = (await session.execute(query)).all()
    return [ChatSummary(chat=chat, last_message=message) for chat, message in rows]


async def chat_summary(session: AsyncSession, chat_id: int) -> ChatSummary:
    [summary] = await list_chats(session, chat_id=chat_id)
    return summary


async def message_page(
    session: AsyncSession,
    message_source: MessageSource,
    chat_id: int,
    *,
    before: int | None,
    limit: int,
) -> MessagePage:
    """The newest `limit` Messages of a Chat older than Message `before`, oldest first.

    uMessage stores a recent window of each Chat (ADR-0003). When a page runs past the oldest
    stored Message, the Messages just older than it are fetched from the Message Source and
    stored too (de-duplicated like any other), so paging carries on through the Chat's whole
    history with no gap or repeat at the boundary, and the cursor stays a stored Message id.
    """
    chat = await session.get(Chat, chat_id)
    if chat is None:
        raise NotFoundError(f"no Chat {chat_id}")
    cursor: Message | None = None
    if before is not None:
        cursor = await session.get(Message, before)
        if cursor is None or cursor.chat_id != chat_id:
            raise NotFoundError(f"no Message {before} in Chat {chat_id}")
    newest_first = await _stored_page(session, chat_id, cursor, limit)
    history_complete = chat.history_complete
    if len(newest_first) < limit and not history_complete:
        try:
            older = await _older_from_source(session, message_source, chat, limit=limit)
        except Exception as exc:
            logger.warning("Couldn't fetch older Messages of Chat %s", chat_id, exc_info=True)
            if not newest_first:
                raise OlderMessagesUnavailableError(str(exc) or type(exc).__name__) from exc
        else:
            await _store_older(session, chat, older)
            history_complete = chat.history_complete
            newest_first = await _stored_page(session, chat_id, cursor, limit)
    return MessagePage(
        messages=newest_first[:limit][::-1],
        has_older=len(newest_first) > limit or not history_complete,
    )


async def _stored_page(
    session: AsyncSession, chat_id: int, cursor: Message | None, limit: int
) -> list[Message]:
    """Up to `limit + 1` stored Messages older than `cursor`, newest first."""
    query = select(Message).where(Message.chat_id == chat_id)
    if cursor is not None:
        query = query.where(
            or_(
                Message.sent_at < cursor.sent_at,
                and_(Message.sent_at == cursor.sent_at, Message.id < cursor.id),
            )
        )
    query = query.order_by(Message.sent_at.desc(), Message.id.desc()).limit(limit + 1)
    return list((await session.scalars(query)).all())


async def _older_from_source(
    session: AsyncSession, message_source: MessageSource, chat: Chat, *, limit: int
) -> OlderMessages:
    """The Messages just older than the Chat's oldest stored one that the Message Source
    knows (a pending Outbound Message's id is only provisional)."""
    oldest = await session.scalar(
        select(Message)
        .where(Message.chat_id == chat.id, ~Message.pending)
        .order_by(Message.sent_at, Message.id)
        .limit(1)
    )
    before = SourceMessageRef(oldest.source_id, oldest.paging_key) if oldest else None
    return await message_source.older_messages(chat.source_id, before=before, limit=limit)


async def _store_older(session: AsyncSession, chat: Chat, older: OlderMessages) -> None:
    if older.messages:
        await session.execute(
            insert(Message)
            .values([_message_row(chat.id, m, chat.excluded) for m in older.messages])
            .on_conflict_do_nothing(index_elements=["chat_id", "source_id"])
        )
    if not older.has_more:
        chat.history_complete = True
    await session.commit()
