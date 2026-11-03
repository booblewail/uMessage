"""An in-process WebSocket client for the app under test.

It drives the ASGI app directly on the test's own event loop (like httpx's ASGITransport
does for HTTP), so it works alongside `LifespanManager` and the async fixtures.
"""

import asyncio
import json
from types import TracebackType
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI

from tests.conftest import API_TOKEN

RECEIVE_TIMEOUT_SECONDS = 5.0


class WebSocketRejectedError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"WebSocket rejected with close code {code}")
        self.code = code


class WebSocketSession:
    def __init__(self, app: FastAPI, path: str, params: dict[str, str]) -> None:
        self._app = app
        self._scope: dict[str, Any] = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "ws",
            "server": ("test", 80),
            "client": ("127.0.0.1", 50000),
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": urlencode(params).encode(),
            "headers": [(b"host", b"test")],
            "subprotocols": [],
        }
        self._to_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._from_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "WebSocketSession":
        self._task = asyncio.create_task(
            self._app(self._scope, self._to_app.get, self._from_app.put)  # type: ignore[arg-type]
        )
        await self._to_app.put({"type": "websocket.connect"})
        reply = await self._next()
        if reply["type"] == "websocket.close":
            await self._task
            raise WebSocketRejectedError(reply.get("code", 1000))
        assert reply["type"] == "websocket.accept", reply
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._to_app.put({"type": "websocket.disconnect", "code": 1000})
        assert self._task is not None
        async with asyncio.timeout(RECEIVE_TIMEOUT_SECONDS):
            await self._task

    async def receive_json(self) -> dict[str, Any]:
        message = await self._next()
        assert message["type"] == "websocket.send", message
        return json.loads(message["text"])

    async def receive_until(self, event_type: str) -> dict[str, Any]:
        """Skip events until one of `event_type` arrives, and return it."""
        while True:
            event = await self.receive_json()
            if event["type"] == event_type:
                return event

    async def _next(self) -> dict[str, Any]:
        async with asyncio.timeout(RECEIVE_TIMEOUT_SECONDS):
            return await self._from_app.get()


def inbox_socket(app: FastAPI, token: str | None = API_TOKEN) -> WebSocketSession:
    """Connect to `/ws` the way the inbox does; entering it waits for `CONNECTED`."""
    return _ConnectedSession(app, "/ws", {"token": token} if token is not None else {})


class _ConnectedSession(WebSocketSession):
    async def __aenter__(self) -> "WebSocketSession":
        await super().__aenter__()
        assert (await self.receive_json()) == {"type": "CONNECTED"}
        return self
