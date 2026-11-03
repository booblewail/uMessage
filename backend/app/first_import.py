"""First Import: the one-time load of existing Chats and recent Messages from the Message Source.

It runs as a tracked background task started at startup until it has completed once; the
completion is stored, so later starts skip it. Progress lives in memory for `/api/status`.

- Waits (re-checking every `retry_seconds`) while the Message Source isn't running, and goes
  back to waiting if it stops mid-import.
- Takes the last `MESSAGES_PER_CHAT` Messages of each Chat active within `IMPORT_WINDOW`,
  leaving out Discord server channels (they aren't Chats).
- Any other failure stops it with the error shown in the status; it runs again on the next
  start. Chats and Messages already stored are never duplicated, so a re-run is safe.
- Before listing Chats it takes the Message Source's cursor for "now" and stores it with the
  completion, so live updates (`app.live_updates`) pick up every Message that arrives while
  it runs (any already imported are not stored twice).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.protocols import ChatKind, MessageSource, MessageSourceUnavailableError
from app.inbox import save_chat, store_cursor
from app.models import FirstImportRecord

logger = logging.getLogger(__name__)

IMPORT_WINDOW = timedelta(days=30)
MESSAGES_PER_CHAT = 50


class FirstImportState(StrEnum):
    WAITING = "waiting"  # for the Message Source to be running
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class FirstImportProgress:
    state: FirstImportState = FirstImportState.WAITING
    chats_total: int | None = None  # known once the Chats have been listed
    chats_imported: int = 0
    error: str | None = field(default=None)


class FirstImport:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        message_source: MessageSource,
        *,
        retry_seconds: float,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._source = message_source
        self._retry_seconds = retry_seconds
        self.progress = FirstImportProgress()

    async def load_completion(self) -> bool:
        """Read whether First Import completed on an earlier start; True if it did."""
        async with self._sessionmaker() as session:
            record = await session.get(FirstImportRecord, 1)
        if record is None:
            return False
        self.progress = FirstImportProgress(
            state=FirstImportState.COMPLETED,
            chats_total=record.chats_imported,
            chats_imported=record.chats_imported,
        )
        return True

    async def run(self) -> None:
        while True:
            self.progress = FirstImportProgress(state=FirstImportState.WAITING)
            try:
                await self._wait_until_source_is_running()
                await self._import()
            except MessageSourceUnavailableError:
                logger.info("The Message Source went away during First Import; waiting for it")
                await asyncio.sleep(self._retry_seconds)
                continue
            except Exception as exc:
                logger.exception("First Import failed; it runs again on the next start")
                self.progress.state = FirstImportState.FAILED
                self.progress.error = str(exc) or type(exc).__name__
            return

    async def _wait_until_source_is_running(self) -> None:
        # Beeper Desktop's API has no "started" notification, so poll its status.
        while True:
            if (await self._source.status()).running:
                return
            await asyncio.sleep(self._retry_seconds)

    async def _import(self) -> None:
        self.progress.state = FirstImportState.RUNNING
        new_messages_from = (await self._source.new_messages(since=None)).cursor
        active_since = datetime.now(UTC) - IMPORT_WINDOW
        listed = await self._source.list_chats(active_since=active_since)
        chats = sorted(
            (
                chat
                for chat in listed
                if chat.kind is not ChatKind.SERVER_CHANNEL and chat.last_activity >= active_since
            ),
            key=lambda chat: chat.last_activity,
            reverse=True,
        )
        self.progress.chats_total = len(chats)
        for chat in chats:
            messages = await self._source.recent_messages(chat.source_id, limit=MESSAGES_PER_CHAT)
            async with self._sessionmaker() as session:
                await save_chat(session, chat, messages)
                await session.commit()
            self.progress.chats_imported += 1
        async with self._sessionmaker() as session:
            session.add(
                FirstImportRecord(completed_at=datetime.now(UTC), chats_imported=len(chats))
            )
            await store_cursor(session, new_messages_from)
            await session.commit()
        self.progress.state = FirstImportState.COMPLETED
