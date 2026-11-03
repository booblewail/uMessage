"""The inbox's open `/ws` WebSockets, and pushing events (e.g. `NEW_MESSAGE`) to all of them."""

import logging

from fastapi import WebSocket, WebSocketDisconnect

from app.schemas import ApiModel, ConnectedEvent

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._sockets: set[WebSocket] = set()

    async def serve(self, websocket: WebSocket) -> None:
        """Accept an (authenticated) WebSocket and keep it open until the client goes away."""
        await websocket.accept()
        self._sockets.add(websocket)
        try:
            await websocket.send_json(_json(ConnectedEvent()))
            while True:
                await websocket.receive_text()  # nothing to read; this notices a disconnect
        except WebSocketDisconnect:
            pass
        finally:
            self._sockets.discard(websocket)

    async def broadcast(self, event: ApiModel) -> None:
        data = _json(event)
        for websocket in list(self._sockets):
            try:
                await websocket.send_json(data)
            except Exception:  # a socket that went away mid-send; its `serve` cleans up
                logger.debug("Dropping a WebSocket that could not be sent to", exc_info=True)
                self._sockets.discard(websocket)


def _json(event: ApiModel) -> object:
    return event.model_dump(mode="json", by_alias=True)
