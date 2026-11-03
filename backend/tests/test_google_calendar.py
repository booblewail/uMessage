"""The Google Calendar adapter: the `events.insert` body it builds, how it uses the client and
the saved sign-in. No network: the Google API client is a fake object here."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from app.adapters.fakes import FakeMessageSource
from app.adapters.google_calendar import SCOPES, GoogleCalendar, entry_body
from app.adapters.protocols import CalendarEntryRequest, CalendarUnavailableError
from app.config import Settings
from tests.conftest import http_client, make_app

DESCRIPTION = "From WhatsApp chat 'Climbing crew':\n> Lea: Thursday 7pm at Boulderhaus"


def timed_request(**changes: Any) -> CalendarEntryRequest:
    values: dict[str, Any] = {
        "title": "Climbing",
        "start": datetime(2026, 11, 5, 18, 0, tzinfo=UTC),
        "end": datetime(2026, 11, 5, 19, 30, tzinfo=UTC),
        "timezone": "Europe/Berlin",
        "location": "Boulderhaus",
        "description": DESCRIPTION,
    }
    return CalendarEntryRequest(**{**values, **changes})


def test_a_timed_entry_is_in_the_users_time_zone() -> None:
    assert entry_body(timed_request()) == {
        "summary": "Climbing",
        "location": "Boulderhaus",
        "description": DESCRIPTION,
        "start": {"dateTime": "2026-11-05T19:00:00+01:00", "timeZone": "Europe/Berlin"},
        "end": {"dateTime": "2026-11-05T20:30:00+01:00", "timeZone": "Europe/Berlin"},
    }


def test_an_all_day_entry_ends_the_day_after_its_last_day() -> None:
    body = entry_body(timed_request(start=date(2026, 11, 7), end=date(2026, 11, 8)))

    assert (body["start"], body["end"]) == ({"date": "2026-11-07"}, {"date": "2026-11-09"})


def test_a_single_all_day_entry_ends_the_next_day() -> None:
    body = entry_body(timed_request(start=date(2026, 12, 31), end=date(2026, 12, 31)))

    assert (body["start"], body["end"]) == ({"date": "2026-12-31"}, {"date": "2027-01-01"})


def test_an_entry_without_a_location_has_none() -> None:
    assert "location" not in entry_body(timed_request(location=None))


@pytest.mark.parametrize(
    "changes",
    [
        {"end": datetime(2026, 11, 5, 17, 0, tzinfo=UTC)},  # before start
        {"start": datetime(2026, 11, 5, 18, 0)},  # naive
        {"start": date(2026, 11, 7), "end": date(2026, 11, 6)},
        {"start": date(2026, 11, 7)},  # all-day start, timed end
    ],
)
def test_an_inconsistent_request_is_a_bug(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        timed_request(**changes)


class FakeEvents:
    """Stands in for `service.events()`: records each insert and answers with an id."""

    def __init__(self) -> None:
        self.inserted: list[tuple[str, dict[str, Any]]] = []

    def insert(self, *, calendarId: str, body: dict[str, Any]) -> "FakeEvents":
        self.inserted.append((calendarId, body))
        return self

    def execute(self) -> dict[str, Any]:
        return {"id": f"gcal-{len(self.inserted)}", "status": "confirmed"}


class FakeService:
    def __init__(self) -> None:
        self.calendar_events = FakeEvents()
        self.credentials: list[Credentials] = []

    def __call__(self, credentials: Credentials) -> "FakeService":
        self.credentials.append(credentials)
        return self

    def events(self) -> FakeEvents:
        return self.calendar_events


def write_token(path: Path, *, expires_in: timedelta, refresh_token: str | None = "refresh-1"):
    expiry = (datetime.now(UTC) + expires_in).replace(tzinfo=None)
    token = {
        "token": "access-1",
        "refresh_token": refresh_token,
        "client_id": "client.apps.googleusercontent.com",
        "client_secret": "secret",
        "scopes": SCOPES,
        "expiry": expiry.isoformat() + "Z",
    }
    path.write_text(json.dumps(token))


def write_garbage(path: Path) -> None:
    path.write_text("{not json")


def read_token(path: Path) -> tuple[dict[str, Any], int]:
    """The saved sign-in, and the file's permission bits."""
    return json.loads(path.read_text()), path.stat().st_mode


@pytest.fixture
def token_path(tmp_path: Path) -> Path:
    return tmp_path / "google-token.json"


async def test_entries_are_inserted_into_the_primary_calendar(token_path: Path) -> None:
    write_token(token_path, expires_in=timedelta(hours=1))
    service = FakeService()
    calendar = GoogleCalendar(token_path, service_factory=service)

    first = await calendar.create_entry(timed_request())
    second = await calendar.create_entry(timed_request(title="Dinner"))

    assert (first, second) == ("gcal-1", "gcal-2")
    assert service.calendar_events.inserted == [
        ("primary", entry_body(timed_request())),
        ("primary", entry_body(timed_request(title="Dinner"))),
    ]
    assert len(service.credentials) == 1  # one client, reused
    assert service.credentials[0].token == "access-1"
    assert (await calendar.status()).connected


async def test_without_a_sign_in_the_calendar_isnt_connected(token_path: Path) -> None:
    calendar = GoogleCalendar(token_path, service_factory=FakeService())

    status = await calendar.status()
    with pytest.raises(CalendarUnavailableError, match="make google-auth"):
        await calendar.create_entry(timed_request())

    assert not status.connected
    assert "Run `make google-auth` to connect Google Calendar" in (status.reason or "")


async def test_signing_in_while_running_connects_it(token_path: Path) -> None:
    calendar = GoogleCalendar(token_path, service_factory=FakeService())
    before = (await calendar.status()).connected

    write_token(token_path, expires_in=timedelta(hours=1))

    assert (before, (await calendar.status()).connected) == (False, True)


async def test_an_unreadable_sign_in_isnt_connected(token_path: Path) -> None:
    write_garbage(token_path)

    status = await GoogleCalendar(token_path).status()

    assert not status.connected
    assert "make google-auth" in (status.reason or "")


async def test_an_expired_sign_in_is_refreshed_and_saved(
    token_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_token(token_path, expires_in=-timedelta(minutes=5))

    def refresh(self: Credentials, request: object) -> None:
        self.token = "access-2"
        self.expiry = (datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None)

    monkeypatch.setattr(Credentials, "refresh", refresh)
    service = FakeService()

    entry_id = await GoogleCalendar(token_path, service_factory=service).create_entry(
        timed_request()
    )

    assert entry_id == "gcal-1"
    assert service.credentials[0].token == "access-2"
    saved, mode = read_token(token_path)
    assert (saved["token"], saved["refresh_token"]) == ("access-2", "refresh-1")
    assert mode & 0o077 == 0  # only the user can read it


async def test_a_revoked_sign_in_isnt_connected(
    token_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_token(token_path, expires_in=-timedelta(minutes=5))

    def refresh(self: Credentials, request: object) -> None:
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(Credentials, "refresh", refresh)
    service = FakeService()
    calendar = GoogleCalendar(token_path, service_factory=service)

    with pytest.raises(CalendarUnavailableError, match="make google-auth"):
        await calendar.create_entry(timed_request())

    assert service.calendar_events.inserted == []


async def test_an_expired_sign_in_without_a_refresh_token_isnt_connected(
    token_path: Path,
) -> None:
    write_token(token_path, expires_in=-timedelta(minutes=5), refresh_token=None)

    status = await GoogleCalendar(token_path).status()

    assert not status.connected


async def test_the_app_starts_without_a_google_sign_in(
    settings: Settings, message_source: FakeMessageSource, token_path: Path
) -> None:
    """Real mode's Calendar with nobody signed in: the app runs; confirming says what to do."""
    app = make_app(settings, message_source, calendar=GoogleCalendar(token_path))

    async with LifespanManager(app) as manager, http_client(manager.app) as client:  # type: ignore[arg-type]
        status = (await client.get("/api/status")).json()["calendar"]

    assert status == {
        "connected": False,
        "reason": "Google Calendar isn't connected. Run `make google-auth` to connect "
        "Google Calendar.",
    }
