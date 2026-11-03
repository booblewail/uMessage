import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.adapters.fakes import FakeCalendar, FakeMessageSource, FakePlanModel
from app.config import BACKEND_DIR, Settings
from app.main import create_app
from tests.clock import FakeClock

API_TOKEN = "test-api-token-0123456789"
# How often the app re-checks for Beeper Desktop, and fetches new Messages, in tests (seconds).
RETRY_SECONDS = 0.01
POLL_SECONDS = 0.01
# How long a test waits for something to happen before failing.
WAIT_SECONDS = 5.0


def migrated_database_url(tmp_path: Path) -> str:
    """A fresh SQLite file migrated to head. Call it outside the event loop (sync fixture)."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'umessage-test.db'}"
    config = Config(BACKEND_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return url


def make_settings(database_url: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "api_token": API_TOKEN,
        "database_url": database_url,
        "umessage_mode": "demo",
        "new_messages_poll_seconds": POLL_SECONDS,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return migrated_database_url(tmp_path)


@pytest.fixture
def settings(database_url: str) -> Settings:
    return make_settings(database_url)


@pytest.fixture
def message_source() -> FakeMessageSource:
    """The Message Source the app under test talks to; tests steer it directly."""
    return FakeMessageSource()


@pytest.fixture
def plan_model() -> FakePlanModel:
    """The Plan Model the app under test asks; tests script its decisions and read its calls."""
    return FakePlanModel()


@pytest.fixture
def clock() -> FakeClock:
    """Plan detection's settle delay only passes when the test calls `clock.advance(...)`."""
    return FakeClock()


def make_app(
    settings: Settings,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel | None = None,
    clock: FakeClock | None = None,
) -> FastAPI:
    return create_app(
        settings,
        message_source=message_source,
        plan_model=plan_model or FakePlanModel(),
        calendar=FakeCalendar(),
        retry_seconds=RETRY_SECONDS,
        settle_sleep=(clock or FakeClock()).sleep,
    )


@pytest.fixture
async def app(
    settings: Settings,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
) -> AsyncIterator[FastAPI]:
    async with LifespanManager(make_app(settings, message_source, plan_model, clock)) as manager:
        yield manager.app  # type: ignore[misc]


def http_client(app: FastAPI, token: str | None = API_TOKEN) -> AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client that sends the right API token."""
    async with http_client(app) as c:
        yield c


@pytest.fixture
async def anonymous_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client that sends no API token."""
    async with http_client(app, token=None) as c:
        yield c


async def wait_for_first_import(client: AsyncClient, *, until: str = "completed") -> dict[str, Any]:
    """Poll `GET /api/status` until First Import reaches `until`; return its status."""
    async with asyncio.timeout(WAIT_SECONDS):
        while True:
            first_import = (await client.get("/api/status")).json()["firstImport"]
            if first_import["state"] == until:
                return first_import
            await asyncio.sleep(RETRY_SECONDS)


async def eventually[T](check: Callable[[], Awaitable[T | None]]) -> T:
    """Re-run `check` until it returns something other than None (or fail after a while)."""
    async with asyncio.timeout(WAIT_SECONDS):
        while True:
            if (result := await check()) is not None:
                return result
            await asyncio.sleep(POLL_SECONDS)


@dataclass(frozen=True, slots=True)
class RunningApp:
    app: FastAPI
    client: AsyncClient


StartApp = Callable[[], Awaitable[AsyncClient]]
StartRunningApp = Callable[[], Awaitable[RunningApp]]


@pytest.fixture
async def start_running_app(
    settings: Settings,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
) -> AsyncIterator[StartRunningApp]:
    """Start the app once the test has filled the fake Message Source; it is returned once
    First Import has completed."""
    async with AsyncExitStack() as stack:

        async def start() -> RunningApp:
            app = make_app(settings, message_source, plan_model, clock)
            manager = await stack.enter_async_context(LifespanManager(app))
            client = await stack.enter_async_context(http_client(manager.app))  # type: ignore[arg-type]
            await wait_for_first_import(client)
            return RunningApp(app=manager.app, client=client)  # type: ignore[arg-type]

        yield start


@pytest.fixture
def start_app(start_running_app: StartRunningApp) -> StartApp:
    """Like `start_running_app`, returning just an HTTP client with the right API token."""

    async def start() -> AsyncClient:
        return (await start_running_app()).client

    return start
