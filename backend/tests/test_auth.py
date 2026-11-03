import pytest
from httpx import AsyncClient


async def test_api_rejects_a_request_without_a_token(anonymous_client: AsyncClient) -> None:
    response = await anonymous_client.get("/api/status")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "authorization",
    ["Bearer not-the-token", "Basic dXNlcjpwYXNz", "test-api-token-0123456789", "Bearer "],
)
async def test_api_rejects_a_wrong_token(anonymous_client: AsyncClient, authorization: str) -> None:
    response = await anonymous_client.get("/api/status", headers={"Authorization": authorization})

    assert response.status_code == 401


async def test_api_accepts_the_right_token(client: AsyncClient) -> None:
    response = await client.get("/api/status")

    assert response.status_code == 200
