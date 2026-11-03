"""`POST /api/events/{id}/confirm` turns a Pending Review Detected Event into a Calendar Entry
(optionally edited first) and the Detected Event Confirmed, exactly once."""

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from asgi_lifespan import LifespanManager
from httpx import AsyncClient, Response

from app.adapters.fakes import FakeCalendar, FakeMessageSource, FakePlanModel
from app.adapters.google_calendar import GoogleCalendar
from app.adapters.protocols import Platform
from app.config import Settings
from tests.clock import FakeClock
from tests.conftest import (
    WAIT_SECONDS,
    RunningApp,
    StartRunningApp,
    eventually,
    http_client,
    make_app,
    make_settings,
    migrated_database_url,
    wait_for_first_import,
)
from tests.plans import days_ahead, detect, new_plan
from tests.sources import a_chat, a_message
from tests.ws import inbox_socket

BERLIN = ZoneInfo("Europe/Berlin")


@pytest.fixture
def settings(database_url: str) -> Settings:
    return make_settings(database_url, user_timezone="Europe/Berlin")


@pytest.fixture
async def running(
    start_running_app: StartRunningApp, message_source: FakeMessageSource
) -> RunningApp:
    message_source.add_chat(
        a_chat("crew", title="Climbing crew", platform=Platform.WHATSAPP),
        [
            a_message(
                "c1",
                sender="Max",
                text="Anyone up for climbing this week?",
                ago=timedelta(minutes=9),
            ),
            a_message(
                "c2", sender="Lea", text="I'm in!\nBut not Wednesday", ago=timedelta(minutes=8)
            ),
            a_message("c3", outbound=True, text="Same", ago=timedelta(minutes=7)),
            a_message("c4", sender="Max", text="Thursday then?", ago=timedelta(minutes=6)),
            a_message("c5", sender="Lea", text="Sure", ago=timedelta(minutes=5)),
        ],
    )
    return await start_running_app()


async def detect_climb(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
    **details: Any,
) -> dict[str, Any]:
    details = {"start": days_ahead(3, time(19)), "location": "Boulderhaus", **details}
    plan_model.will_decide(new_plan("Climbing", **details))
    async with inbox_socket(running.app) as socket:
        return await detect(
            socket,
            message_source,
            clock,
            settings,
            "crew",
            "Thursday 7pm at Boulderhaus",
            sender="Lea",
        )


@pytest.fixture
async def climb(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> dict[str, Any]:
    """Climbing with the crew, Thursday (in 3 days) at 19:00 Berlin time, no end given."""
    return await detect_climb(running, message_source, plan_model, clock, settings)


async def confirm(client: AsyncClient, event: dict[str, Any], **overrides: Any) -> Response:
    url = f"/api/events/{event['id']}/confirm"
    return await client.post(url, json=overrides) if overrides else await client.post(url)


async def event_status(client: AsyncClient, event: dict[str, Any]) -> str:
    events = (await client.get("/api/events")).json()["events"]
    return next(e["status"] for e in events if e["id"] == event["id"])


def local(day_offset: int, at: time) -> datetime:
    return datetime.combine(date.today() + timedelta(days=day_offset), at, tzinfo=BERLIN)


def iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


# --- Confirming as detected -----------------------------------------------------------------


async def test_confirming_creates_a_calendar_entry_and_confirms_the_detected_event(
    running: RunningApp, climb: dict[str, Any], calendar: FakeCalendar
) -> None:
    response = await confirm(running.client, climb)

    assert response.status_code == 200, response.text
    confirmed = response.json()
    [(entry_id, entry)] = calendar.entries.items()
    assert confirmed["status"] == "confirmed"
    assert confirmed["calendarEntryId"] == entry_id
    assert entry.title == "Climbing"
    assert entry.start == local(3, time(19))
    # The Chat didn't say when it ends: it gets the default length (an hour).
    assert entry.end == local(3, time(20))
    assert entry.timezone == "Europe/Berlin"
    assert entry.location == "Boulderhaus"
    assert not entry.all_day
    assert confirmed["end"] == iso_utc(local(3, time(20)))
    assert await event_status(running.client, climb) == "confirmed"


async def test_the_calendar_entry_quotes_the_chat_up_to_the_anchor_message(
    running: RunningApp,
    climb: dict[str, Any],
    calendar: FakeCalendar,
    message_source: FakeMessageSource,
) -> None:
    async with inbox_socket(running.app) as socket:
        later = a_message("later", sender="Max", text="See you there", at=datetime.now(UTC))
        message_source.receive("crew", later)
        await socket.receive_until("NEW_MESSAGE")
    await confirm(running.client, climb)

    [entry] = calendar.entries.values()
    assert entry.description == (
        "From WhatsApp chat 'Climbing crew':\n"
        "> Lea: I'm in!\n"
        "> But not Wednesday\n"
        "> You: Same\n"
        "> Max: Thursday then?\n"
        "> Lea: Sure\n"
        "> Lea: Thursday 7pm at Boulderhaus"
    )


async def test_confirming_pushes_the_confirmed_detected_event(
    running: RunningApp, climb: dict[str, Any]
) -> None:
    async with inbox_socket(running.app) as socket:
        response = await confirm(running.client, climb)
        pushed = await socket.receive_until("EVENT_DETECTED")

    assert pushed == {"type": "EVENT_DETECTED", "change": "updated", "event": response.json()}


async def test_the_anchor_message_shows_the_confirmed_detected_event(
    running: RunningApp, climb: dict[str, Any]
) -> None:
    confirmed = (await confirm(running.client, climb)).json()

    page = (await running.client.get(f"/api/chats/{climb['chatId']}/messages")).json()
    anchor = next(m for m in page["messages"] if m["id"] == climb["anchorMessageId"])
    assert anchor["detectedEvents"] == [confirmed]


async def test_a_detected_event_with_an_end_keeps_it(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
    calendar: FakeCalendar,
) -> None:
    climb = await detect_climb(
        running, message_source, plan_model, clock, settings, end=days_ahead(3, time(21, 30))
    )

    await confirm(running.client, climb)

    [entry] = calendar.entries.values()
    assert (entry.start, entry.end) == (local(3, time(19)), local(3, time(21, 30)))


async def test_an_all_day_detected_event_becomes_an_all_day_calendar_entry(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
    calendar: FakeCalendar,
) -> None:
    trip = await detect_climb(
        running,
        message_source,
        plan_model,
        clock,
        settings,
        start=days_ahead(5),
        end=days_ahead(6),
        all_day=True,
    )

    confirmed = (await confirm(running.client, trip)).json()

    [entry] = calendar.entries.values()
    assert entry.all_day
    first, last = date.today() + timedelta(days=5), date.today() + timedelta(days=6)
    assert (entry.start, entry.end) == (first, last)  # last day inclusive
    assert (confirmed["start"], confirmed["end"]) == (trip["start"], trip["end"])


# --- Editing before confirming --------------------------------------------------------------


async def test_overrides_change_the_calendar_entry_and_the_detected_event(
    running: RunningApp, climb: dict[str, Any], calendar: FakeCalendar
) -> None:
    start, end = local(4, time(18, 30)), local(4, time(20))

    response = await confirm(
        running.client,
        climb,
        title="Bouldering",
        start=start.isoformat(),
        end=iso_utc(end),
        location="Kletterhalle",
    )

    assert response.status_code == 200, response.text
    confirmed = response.json()
    [entry] = calendar.entries.values()
    assert (entry.title, entry.start, entry.end, entry.location) == (
        "Bouldering",
        start,
        end,
        "Kletterhalle",
    )
    assert {k: confirmed[k] for k in ("title", "start", "end", "allDay", "location")} == {
        "title": "Bouldering",
        "start": iso_utc(start),
        "end": iso_utc(end),
        "allDay": False,
        "location": "Kletterhalle",
    }


async def test_an_empty_location_or_end_is_cleared(
    running: RunningApp, climb: dict[str, Any], calendar: FakeCalendar
) -> None:
    await confirm(running.client, climb, location="  ", end=None)

    [entry] = calendar.entries.values()
    assert entry.location is None
    assert entry.end == entry.start + timedelta(hours=1)


async def test_a_timed_detected_event_can_be_confirmed_as_all_day(
    running: RunningApp, climb: dict[str, Any], calendar: FakeCalendar
) -> None:
    first, last = date.today() + timedelta(days=3), date.today() + timedelta(days=4)

    response = await confirm(
        running.client, climb, allDay=True, start=first.isoformat(), end=last.isoformat()
    )

    assert response.status_code == 200, response.text
    [entry] = calendar.entries.values()
    assert (entry.all_day, entry.start, entry.end) == (True, first, last)
    confirmed = response.json()
    midnight = datetime.combine(first, time(), tzinfo=BERLIN)
    assert (confirmed["allDay"], confirmed["start"]) == (True, iso_utc(midnight))
    assert confirmed["end"] == iso_utc(midnight + timedelta(days=1))


async def test_a_single_all_day_needs_no_end(
    running: RunningApp, climb: dict[str, Any], calendar: FakeCalendar
) -> None:
    day = date.today() + timedelta(days=3)

    confirmed = (await confirm(running.client, climb, allDay=True, start=day.isoformat())).json()

    [entry] = calendar.entries.values()
    assert (entry.start, entry.end) == (day, day)
    assert confirmed["end"] is None


@pytest.mark.parametrize(
    ("overrides", "complaint"),
    [
        ({"title": "   "}, "title"),
        ({"end": "2020-01-01T10:00:00Z"}, "end"),
        ({"start": "2030-01-01T10:00:00Z", "end": "2030-01-01T09:00:00Z"}, "end"),
        ({"start": "2030-01-01T10:00:00Z", "end": "2030-01-01T10:00:00Z"}, "end"),
        ({"start": "2030-01-01T10:00:00"}, "time zone"),
        ({"start": "2030-01-01"}, "date and time"),
        ({"allDay": True, "start": "2030-01-01T10:00:00Z"}, "date"),
        ({"allDay": True, "start": "2030-01-02", "end": "2030-01-01"}, "end"),
        ({"allDay": True}, "start"),
        ({"colour": "red"}, "colour"),
    ],
)
async def test_invalid_overrides_are_rejected(
    running: RunningApp,
    climb: dict[str, Any],
    calendar: FakeCalendar,
    overrides: dict[str, Any],
    complaint: str,
) -> None:
    response = await confirm(running.client, climb, **overrides)

    assert response.status_code == 422, response.text
    assert complaint in str(response.json()["detail"])
    assert calendar.entries == {}
    assert await event_status(running.client, climb) == "pending_review"


# --- Exactly once ---------------------------------------------------------------------------


async def test_confirming_twice_creates_one_calendar_entry(
    running: RunningApp, climb: dict[str, Any], calendar: FakeCalendar
) -> None:
    first = await confirm(running.client, climb)
    second = await confirm(running.client, climb)

    assert (first.status_code, second.status_code) == (200, 409)
    assert "confirmed" in second.json()["detail"]
    assert len(calendar.entries) == 1


async def test_two_confirms_at_once_create_one_calendar_entry(
    running: RunningApp, climb: dict[str, Any], calendar: FakeCalendar
) -> None:
    calendar.answering.clear()  # the first to reach the Calendar waits there
    requests = [asyncio.create_task(confirm(running.client, climb)) for _ in range(2)]

    done, _ = await asyncio.wait(requests, timeout=WAIT_SECONDS, return_when="FIRST_COMPLETED")
    assert done, "both confirms reached the Calendar"
    await eventually(lambda: _true_when(calendar.in_flight == 1))  # the other is on its way
    calendar.answering.set()
    responses = await asyncio.gather(*requests)

    assert sorted(r.status_code for r in responses) == [200, 409]
    assert len(calendar.entries) == 1
    assert await event_status(running.client, climb) == "confirmed"


async def test_a_detected_event_being_confirmed_cant_be_dismissed(
    running: RunningApp, climb: dict[str, Any], calendar: FakeCalendar
) -> None:
    calendar.answering.clear()
    confirming = asyncio.create_task(confirm(running.client, climb))
    await eventually(lambda: _true_when(calendar.in_flight == 1))

    dismissed = await running.client.post(f"/api/events/{climb['id']}/dismiss")
    calendar.answering.set()

    assert dismissed.status_code == 409
    assert (await confirming).status_code == 200


async def _true_when(condition: bool) -> bool | None:
    return True if condition else None


async def test_a_confirm_cut_short_is_pending_review_again_after_a_restart(
    running: RunningApp,
    climb: dict[str, Any],
    calendar: FakeCalendar,
    settings: Settings,
    message_source: FakeMessageSource,
) -> None:
    calendar.answering.clear()
    confirming = asyncio.create_task(confirm(running.client, climb))
    await eventually(lambda: _true_when(calendar.in_flight == 1))
    confirming.cancel()  # the app stops (or crashes) while the Calendar is being asked
    await asyncio.gather(confirming, return_exceptions=True)
    assert await event_status(running.client, climb) == "confirming"

    restarted_calendar = FakeCalendar()
    app = make_app(settings, message_source, calendar=restarted_calendar)
    async with LifespanManager(app) as manager, http_client(manager.app) as client:  # type: ignore[arg-type]
        assert await event_status(client, climb) == "pending_review"
        assert (await confirm(client, climb)).status_code == 200

    assert len(restarted_calendar.entries) == 1


async def test_confirming_again_after_a_crash_once_the_calendar_entry_exists_makes_no_second(
    running: RunningApp,
    climb: dict[str, Any],
    calendar: FakeCalendar,
    settings: Settings,
    message_source: FakeMessageSource,
) -> None:
    """The Calendar created the entry, but the app stopped before hearing back (so before it
    stored Confirmed): after the restart it is Pending Review again, and confirming it once
    more finds the same Calendar Entry instead of creating another."""
    calendar.loses_answers = True
    confirming = asyncio.create_task(confirm(running.client, climb))
    await eventually(lambda: _true_when(len(calendar.entries) == 1))
    confirming.cancel()
    await asyncio.gather(confirming, return_exceptions=True)
    [created] = calendar.entries

    calendar.loses_answers = False
    app = make_app(settings, message_source, calendar=calendar)  # the same (Google's) calendar
    async with LifespanManager(app) as manager, http_client(manager.app) as client:  # type: ignore[arg-type]
        assert await event_status(client, climb) == "pending_review"
        response = await confirm(client, climb, title="Climbing at Boulderhaus")

    assert response.status_code == 200, response.text
    assert response.json()["calendarEntryId"] == created
    assert list(calendar.entries) == [created]


@pytest.fixture
def other_database_url(tmp_path: Path) -> str:
    """A second uMessage database (migrated outside the event loop, like `database_url`)."""
    (tmp_path / "other").mkdir()
    return migrated_database_url(tmp_path / "other")


async def test_calendar_entry_keys_differ_between_databases(
    running: RunningApp,
    climb: dict[str, Any],
    calendar: FakeCalendar,
    other_database_url: str,
    message_source: FakeMessageSource,
) -> None:
    """Another uMessage database (e.g. after starting over) numbers its Detected Events from 1
    again; its Calendar Entries must not be mistaken for this one's."""
    await confirm(running.client, climb)
    other_settings = make_settings(other_database_url, user_timezone="Europe/Berlin")
    plan_model, clock = FakePlanModel(), FakeClock()
    plan_model.will_decide(new_plan("Climbing", start=days_ahead(4, time(19))))
    app = make_app(other_settings, message_source, plan_model, clock, calendar)
    async with LifespanManager(app) as manager, http_client(manager.app) as client:  # type: ignore[arg-type]
        await wait_for_first_import(client)
        async with inbox_socket(manager.app) as socket:  # type: ignore[arg-type]
            other = await detect(
                socket, message_source, clock, other_settings, "crew", "Or Friday 7pm?"
            )
        assert other["id"] == climb["id"]
        response = await confirm(client, other)

    assert response.status_code == 200, response.text
    first, second = (request.entry_key for request in calendar.entries.values())
    assert first != second


# --- When it can't be confirmed -------------------------------------------------------------


async def test_a_calendar_failure_leaves_the_detected_event_pending_review(
    running: RunningApp, climb: dict[str, Any], calendar: FakeCalendar
) -> None:
    calendar.failing = True

    failed = await confirm(running.client, climb)

    assert failed.status_code == 502
    assert "Calendar Entry" in failed.json()["detail"]
    assert await event_status(running.client, climb) == "pending_review"

    calendar.failing = False
    assert (await confirm(running.client, climb)).status_code == 200
    assert len(calendar.entries) == 1


async def test_a_disconnected_calendar_is_service_unavailable(
    running: RunningApp, climb: dict[str, Any], calendar: FakeCalendar
) -> None:
    calendar.connected = False

    response = await confirm(running.client, climb)

    assert response.status_code == 503
    assert response.json()["detail"] == "The fake Calendar isn't connected"
    assert await event_status(running.client, climb) == "pending_review"


async def test_a_dismissed_detected_event_cant_be_confirmed(
    running: RunningApp, climb: dict[str, Any], calendar: FakeCalendar
) -> None:
    await running.client.post(f"/api/events/{climb['id']}/dismiss")

    response = await confirm(running.client, climb)

    assert response.status_code == 409
    assert "dismissed" in response.json()["detail"]
    assert calendar.entries == {}


async def test_a_confirmed_detected_event_cant_be_dismissed(
    running: RunningApp, climb: dict[str, Any]
) -> None:
    await confirm(running.client, climb)

    response = await running.client.post(f"/api/events/{climb['id']}/dismiss")

    assert response.status_code == 409
    assert await event_status(running.client, climb) == "confirmed"


async def test_confirming_an_unknown_detected_event_is_not_found(running: RunningApp) -> None:
    response = await running.client.post("/api/events/12345/confirm")

    assert response.status_code == 404


async def test_confirming_needs_the_api_token(anonymous_client: AsyncClient) -> None:
    response = await anonymous_client.post("/api/events/1/confirm")

    assert response.status_code == 401


# --- Calendar status ------------------------------------------------------------------------


async def test_status_reports_the_calendar(client: AsyncClient, calendar: FakeCalendar) -> None:
    connected = (await client.get("/api/status")).json()["calendar"]
    calendar.connected = False
    disconnected = (await client.get("/api/status")).json()["calendar"]

    assert connected == {"connected": True, "reason": None}
    assert disconnected == {"connected": False, "reason": "The fake Calendar isn't connected"}


async def test_without_a_google_sign_in_confirming_says_how_to_connect(
    climb: dict[str, Any], settings: Settings, message_source: FakeMessageSource, tmp_path: Path
) -> None:
    google = GoogleCalendar(tmp_path / "no-google-token.json")
    app = make_app(settings, message_source, calendar=google)  # real mode, nobody signed in
    async with LifespanManager(app) as manager, http_client(manager.app) as client:  # type: ignore[arg-type]
        response = await confirm(client, climb)
        status = await event_status(client, climb)

    assert response.status_code == 503
    assert "Run `make google-auth` to connect Google Calendar" in response.json()["detail"]
    assert status == "pending_review"
