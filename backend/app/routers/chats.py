import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import inbox, replies
from app.adapters.protocols import MessageSource, Platform
from app.db import get_session
from app.dependencies import get_connections, get_inbox_lock, get_message_source
from app.schemas import (
    ChatsOut,
    MessageOut,
    MessagePageOut,
    ReplyIn,
    chat_out,
    message_out,
)
from app.ws_manager import ConnectionManager

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/chats")
async def list_chats(session: Session, platform: Platform | None = None) -> ChatsOut:
    """Every Chat in the inbox, newest first; `platform` narrows it to one Platform."""
    summaries = await inbox.list_chats(session, platform=platform)
    return ChatsOut(chats=[chat_out(summary) for summary in summaries])


@router.get("/chats/{chat_id}/messages")
async def list_messages(
    chat_id: int,
    session: Session,
    message_source: Annotated[MessageSource, Depends(get_message_source)],
    before: Annotated[int | None, Query(description="A Message id: only older ones")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MessagePageOut:
    """A page of a Chat's Messages: the newest `limit` before `before`, oldest first.

    Paging back goes past the stored Messages to older ones from Beeper Desktop; 503 if
    those are needed while Beeper Desktop can't give them."""
    try:
        page = await inbox.message_page(
            session, message_source, chat_id, before=before, limit=limit
        )
    except inbox.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except inbox.OlderMessagesUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Older Messages can't be loaded from Beeper Desktop right now: {exc}",
        ) from exc
    return MessagePageOut(
        messages=[message_out(message) for message in page.messages],
        has_older=page.has_older,
        older_cursor=page.messages[0].id if page.has_older else None,
    )


@router.post("/chats/{chat_id}/messages", status_code=status.HTTP_201_CREATED)
async def send_message(
    chat_id: int,
    body: ReplyIn,
    session: Session,
    message_source: Annotated[MessageSource, Depends(get_message_source)],
    connections: Annotated[ConnectionManager, Depends(get_connections)],
    inbox_lock: Annotated[asyncio.Lock, Depends(get_inbox_lock)],
) -> MessageOut:
    """Send a Message to the Chat through Beeper Desktop; returns the stored Outbound Message
    (also pushed as `NEW_MESSAGE`). 502 if Beeper Desktop didn't send it: nothing is stored."""
    try:
        return await replies.send_reply(
            session, message_source, connections, inbox_lock, chat_id=chat_id, text=body.text
        )
    except inbox.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except replies.SendFailedError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Beeper Desktop couldn't send the Message: {exc}"
        ) from exc
