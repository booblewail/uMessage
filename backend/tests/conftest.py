from collections.abc import AsyncIterator
from pathlib import Path

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


@pytest.fixture
async def app(settings: Settings, message_source: FakeMessageSource) -> AsyncIterator[FastAPI]:
    application = create_app(
        settings,
        message_source=message_source,
        plan_model=FakePlanModel(),
        calendar=FakeCalendar(),
    )
    async with LifespanManager(application) as manager:
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
