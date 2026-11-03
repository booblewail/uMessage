"""Demo mode (`UMESSAGE_MODE=demo`) runs the real app with fake adapters and no credentials."""

import pytest
from asgi_lifespan import LifespanManager

from app.main import build_app
from tests.conftest import http_client, make_settings


@pytest.mark.parametrize("beeper_running", [True, False])
async def test_demo_mode_reports_the_configured_beeper_desktop_state(
    database_url: str, beeper_running: bool
) -> None:
    settings = make_settings(
        database_url,
        umessage_mode="demo",
        demo_beeper_running=beeper_running,
    )

    async with LifespanManager(build_app(settings)) as manager, http_client(manager.app) as client:
        body = (await client.get("/api/status")).json()

    assert body == {
        "mode": "demo",
        "messageSource": {"name": "Beeper Desktop", "running": beeper_running},
    }
