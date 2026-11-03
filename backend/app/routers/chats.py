from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import inbox
from app.adapters.protocols import ChatKind, Platform
from app.db import get_session
from app.schemas import ChatOut, ChatsOut, LastMessageOut, MessageOut, MessagePageOut

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/chats")
async def list_chats(session: Session, platform: Platform | None = None) -> ChatsOut:
    """Every Chat in the inbox, newest first; `platform` narrows it to one Platform."""
    summaries = await inbox.list_chats(session, platform=platform)
    return ChatsOut(chats=[_chat_out(summary) for summary in summaries])


@router.get("/chats/{chat_id}/messages")
async def list_messages(
    chat_id: int,
    session: Session,
    before: Annotated[int | None, Query(description="A Message id: only older ones")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MessagePageOut:
    """A page of a Chat's Messages: the newest `limit` before `before`, oldest first."""
    try:
        page = await inbox.message_page(session, chat_id, before=before, limit=limit)
    except inbox.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return MessagePageOut(
        messages=[
            MessageOut(
                id=message.id,
                chat_id=message.chat_id,
                sender_name=message.sender_name,
                sent_at=message.sent_at,
                text=message.text,
                outbound=message.outbound,
            )
            for message in page.messages
        ],
        has_older=page.has_older,
        older_cursor=page.messages[0].id if page.has_older else None,
    )


def _chat_out(summary: inbox.ChatSummary) -> ChatOut:
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
