"""The real Beeper Desktop Message Source, driven through the API."""

import socket
from collections.abc import Callable

import httpx
from asgi_lifespan import LifespanManager

from app.adapters.beeper_desktop import BeeperDesktopMessageSource
from app.adapters.fakes import FakeCalendar, FakePlanModel
from app.main import create_app
from tests.conftest import http_client, make_settings

Handler = Callable[[httpx.Request], httpx.Response]


async def reported_status(database_url: str, source: BeeperDesktopMessageSource) -> object:
    app = create_app(
        make_settings(database_url, umessage_mode="real"),
        message_source=source,
        plan_model=FakePlanModel(),
        calendar=FakeCalendar(),
    )
    async with LifespanManager(app) as manager, http_client(manager.app) as client:
        return (await client.get("/api/status")).json()


def beeper_answering(handler: Handler) -> BeeperDesktopMessageSource:
    return BeeperDesktopMessageSource(
        "http://127.0.0.1:23373", transport=httpx.MockTransport(handler)
    )


def unused_local_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_beeper_desktop_answering_counts_as_running(database_url: str) -> None:
    # Beeper Desktop's API rejects requests without its own token; it is still running.
    body = await reported_status(database_url, beeper_answering(lambda _: httpx.Response(401)))

    assert body == {"mode": "real", "messageSource": {"name": "Beeper Desktop", "running": True}}


async def test_beeper_desktop_timing_out_counts_as_not_running(database_url: str) -> None:
    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    body = await reported_status(database_url, beeper_answering(hang))

    assert body == {"mode": "real", "messageSource": {"name": "Beeper Desktop", "running": False}}


async def test_nothing_listening_where_beeper_desktop_should_be_counts_as_not_running(
    database_url: str,
) -> None:
    source = BeeperDesktopMessageSource(f"http://127.0.0.1:{unused_local_port()}")

    body = await reported_status(database_url, source)

    assert body == {"mode": "real", "messageSource": {"name": "Beeper Desktop", "running": False}}
