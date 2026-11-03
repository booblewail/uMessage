import secrets

from fastapi import APIRouter, WebSocket, status

router = APIRouter()


@router.websocket("/ws")
async def inbox_socket(websocket: WebSocket) -> None:
    """Live inbox events (`CONNECTED`, then `NEW_MESSAGE`s). Needs `?token=<API_TOKEN>`:
    browsers can't send an Authorization header on a WebSocket."""
    token = websocket.query_params.get("token", "")
    expected = websocket.app.state.settings.api_token.get_secret_value()
    if not secrets.compare_digest(token.encode(), expected.encode()):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.app.state.connections.serve(websocket)
