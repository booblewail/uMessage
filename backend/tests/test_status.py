from httpx import AsyncClient

from app.adapters.fakes import FakeMessageSource


async def test_status_reports_beeper_desktop_running(
    client: AsyncClient, message_source: FakeMessageSource
) -> None:
    message_source.running = True

    response = await client.get("/api/status")

    assert response.status_code == 200
    assert response.json() == {
        "mode": "demo",
        "messageSource": {"name": "Beeper Desktop", "running": True},
    }


async def test_status_reports_beeper_desktop_not_running(
    client: AsyncClient, message_source: FakeMessageSource
) -> None:
    message_source.running = False

    response = await client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["messageSource"] == {"name": "Beeper Desktop", "running": False}


async def test_status_follows_beeper_desktop_starting_and_stopping(
    client: AsyncClient, message_source: FakeMessageSource
) -> None:
    message_source.running = False
    before = (await client.get("/api/status")).json()["messageSource"]["running"]

    message_source.running = True
    after = (await client.get("/api/status")).json()["messageSource"]["running"]

    assert (before, after) == (False, True)


async def test_frontend_origin_may_call_the_api(client: AsyncClient) -> None:
    response = await client.options(
        "/api/status",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
