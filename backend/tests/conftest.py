import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
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

API_TOKEN = "test-api-token-0123456789"
# How often First Import re-checks for Beeper Desktop in tests (seconds).
RETRY_SECONDS = 0.01
# How long a test waits for First Import to reach a state before failing.
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


def make_app(settings: Settings, message_source: FakeMessageSource) -> FastAPI:
    return create_app(
        settings,
        message_source=message_source,
        plan_model=FakePlanModel(),
        calendar=FakeCalendar(),
        first_import_retry_seconds=RETRY_SECONDS,
    )


@pytest.fixture
async def app(settings: Settings, message_source: FakeMessageSource) -> AsyncIterator[FastAPI]:
    async with LifespanManager(make_app(settings, message_source)) as manager:
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


StartApp = Callable[[], Awaitable[AsyncClient]]


@pytest.fixture
async def start_app(
    settings: Settings, message_source: FakeMessageSource
) -> AsyncIterator[StartApp]:
    """Start the app once the test has filled the fake Message Source; the returned client
    is ready once First Import has completed."""
    async with AsyncExitStack() as stack:

        async def start() -> AsyncClient:
            app = make_app(settings, message_source)
            manager = await stack.enter_async_context(LifespanManager(app))
            client = await stack.enter_async_context(http_client(manager.app))  # type: ignore[arg-type]
            await wait_for_first_import(client)
            return client

        yield start
