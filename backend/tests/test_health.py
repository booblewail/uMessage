from httpx import AsyncClient


async def test_health_answers_without_a_token(anonymous_client: AsyncClient) -> None:
    response = await anonymous_client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
