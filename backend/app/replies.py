"""Replying from the inbox: send a Message through the Message Source, store it as an Outbound
Message, hand it to plan detection and push it to the inbox. Nothing is stored unless the
Message Source accepted it."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app import inbox
from app.adapters.protocols import MessageSource
from app.live_updates import new_message_event
from app.models import Chat
from app.plan_detection import PlanDetection
from app.schemas import MessageOut
from app.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)


class SendFailedError(Exception):
    """The Message Source didn't accept the Message."""


async def send_reply(
    session: AsyncSession,
    message_source: MessageSource,
    connections: ConnectionManager,
    inbox_lock: asyncio.Lock,
    plan_detection: PlanDetection,
    *,
    chat_id: int,
    text: str,
) -> MessageOut:
    chat = await session.get(Chat, chat_id)
    if chat is None:
        raise inbox.NotFoundError(f"no Chat {chat_id}")
    # Under the inbox lock, live updates can't see this Message come back before it's stored.
    async with inbox_lock:
        try:
            sent = await message_source.send_message(chat.source_id, text)
        except Exception as exc:
            logger.warning("Sending a Message to Chat %s failed", chat_id, exc_info=True)
            raise SendFailedError(str(exc) or type(exc).__name__) from exc
        message = await inbox.save_sent_message(session, chat_id, sent, text)
        await session.commit()
        event = await new_message_event(session, message.id)
    await plan_detection.message_arrived(chat_id, text)  # a reply can make a plan too
    await connections.broadcast(event)
    return event.message
