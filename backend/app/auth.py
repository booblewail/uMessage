"""Static bearer-token authentication for `/api/*` (ADR-0002: single user, no accounts)."""

import secrets

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


async def require_api_token(request: Request) -> None:
    credentials: HTTPAuthorizationCredentials | None = await _bearer(request)
    expected = request.app.state.settings.api_token.get_secret_value()
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or wrong API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
