"""Message Source backed by Beeper Desktop's local API (ADR-0003, proposed).

For now it only answers `status()`, by checking whether anything answers HTTP at the
Beeper Desktop API address; the Phase 0 spike (#2) and #13 fill in the rest.
"""

from collections.abc import Sequence
from datetime import datetime

import httpx

from app.adapters.protocols import BEEPER_DESKTOP, MessageSourceStatus, SourceChat, SourceMessage

STATUS_TIMEOUT_SECONDS = 2.0


class BeeperDesktopMessageSource:
    def __init__(self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None):
        self._base_url = base_url
        self._transport = transport

    async def status(self) -> MessageSourceStatus:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, transport=self._transport, timeout=STATUS_TIMEOUT_SECONDS
            ) as client:
                await client.get("/")
        except httpx.TransportError:
            return MessageSourceStatus(name=BEEPER_DESKTOP, running=False)
        # Any HTTP answer (even 401/404) means Beeper Desktop's API is up.
        return MessageSourceStatus(name=BEEPER_DESKTOP, running=True)

    # TODO(#13): map `GET /v1/chats/search?lastActivityAfter=` (paging with its cursor) onto
    # SourceChat: `network` -> Platform (skip other networks), `type` plus whatever Phase 0
    # (#2) finds marks a Discord server channel -> ChatKind, `lastActivity` -> last_activity.
    async def list_chats(self, *, active_since: datetime) -> Sequence[SourceChat]:
        raise NotImplementedError(_NOT_BUILT)

    # TODO(#13): map `GET /v1/chats/{chatID}/messages` (paging back with
    # `cursor=oldestCursor&direction=before`) onto SourceMessage: text Messages only,
    # `isSender` -> outbound, `senderID` -> sender_name via the Chat's participants.
    async def recent_messages(self, chat_source_id: str, *, limit: int) -> Sequence[SourceMessage]:
        raise NotImplementedError(_NOT_BUILT)


_NOT_BUILT = "Reading Chats from Beeper Desktop is not built yet (#13)"
