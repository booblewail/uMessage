"""Live updates: after First Import, fetch new Messages from the Message Source, store them, hand
each one to plan detection and push it to the inbox as `NEW_MESSAGE`.

It runs as one tracked background task for the life of the app. Each fetch starts from the
stored cursor and stores the Messages together with the next cursor in one transaction, so
a restart (or the laptop sleeping) neither loses nor repeats a Message: whatever arrived
meanwhile comes with the next fetch. While the Message Source can't be reached it keeps
retrying every `retry_seconds`. Discord server channels are left out (they aren't Chats).
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import inbox
from app.adapters.protocols import ChatKind, MessageSource, MessageSourceUnavailableError
from app.models import Message
from app.plan_detection import PlanDetection
from app.schemas import NewMessageEvent, chat_out, message_out
from app.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)


class LiveUpdates:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        message_source: MessageSource,
        connections: ConnectionManager,
        inbox_lock: asyncio.Lock,
        plan_detection: PlanDetection,
        *,
        poll_seconds: float,
        retry_seconds: float,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._source = message_source
        self._connections = connections
        self._plan_detection = plan_detection
        # Held while fetching + storing, and while sending + storing (`inbox.send`), so the
        # echo of a Message being sent is never stored before the Message itself.
        self._inbox_lock = inbox_lock
        self._poll_seconds = poll_seconds
        self._retry_seconds = retry_seconds

    async def run(self) -> None:
        while True:
            try:
                await self.fetch_once()
                delay = self._poll_seconds
            except MessageSourceUnavailableError:
                delay = self._retry_seconds
            except Exception:
                logger.exception("Fetching new Messages failed; retrying")
                delay = self._retry_seconds
            await asyncio.sleep(delay)

    async def fetch_once(self) -> None:
        async with self._inbox_lock:
            async with self._sessionmaker() as session:
                cursor = await inbox.stored_cursor(session)
            new = await self._source.new_messages(since=cursor)
            async with self._sessionmaker() as session:
                stored: list[int] = []
                for chat, message in new.messages:
                    if chat.kind is ChatKind.SERVER_CHANNEL:
                        continue
                    message_id = await inbox.save_new_message(session, chat, message)
                    if message_id is not None:
                        stored.append(message_id)
                if new.cursor != cursor:
                    await inbox.store_cursor(session, new.cursor)
                await session.commit()
                events = [await new_message_event(session, message_id) for message_id in stored]
        for event in events:
            # Scheduled before it is pushed: once the inbox has it, its Chat's check is set.
            await self._plan_detection.message_arrived(event.chat_id, event.message.text)
            await self._connections.broadcast(event)


async def new_message_event(session: AsyncSession, message_id: int) -> NewMessageEvent:
    message = await session.get_one(Message, message_id)
    summary = await inbox.chat_summary(session, message.chat_id)
    return NewMessageEvent(
        chat_id=message.chat_id, message=message_out(message), chat=chat_out(summary)
    )
