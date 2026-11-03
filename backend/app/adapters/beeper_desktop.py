"""Message Source backed by Beeper Desktop's local API (ADR-0003, proposed).

For now it only answers `status()`, by checking whether anything answers HTTP at the
Beeper Desktop API address; the Phase 0 spike (#2) and #13 fill in the rest.
"""

import httpx

from app.adapters.protocols import BEEPER_DESKTOP, MessageSourceStatus

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
