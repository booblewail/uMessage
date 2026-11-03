"""The "already on your calendar" hint (#12): a Detected Event from a Chat that already has an
upcoming Calendar Entry (another Confirmed Detected Event of that Chat whose start, or for an
all-day one its last day, isn't past) lists it in `existingCalendarEntries`."""

from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from app.adapters.fakes import FakeMessageSource, FakePlanModel
from app.config import Settings
from tests.clock import FakeClock
from tests.conftest import RunningApp, StartRunningApp, make_settings
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
    message_source.add_chat(a_chat("mum", title="Mum"), [a_message("m0")])
    message_source.add_chat(a_chat("crew", title="Crew"), [a_message("c0")])
    return await start_running_app()


@pytest.fixture
async def plans(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> dict[str, dict[str, Any]]:
    """Mum: dinner (in 3 days) and lunch (in 5); Crew: a climb (in 2). All Pending Review."""
    plan_model.will_decide(
        new_plan("Dinner at Mum's", start=days_ahead(3)),
        new_plan("Sunday lunch", start=days_ahead(5, time(13))),
        new_plan("Climb", start=days_ahead(2)),
    )
    async with inbox_socket(running.app) as socket:
        return {
            "dinner": await detect(socket, message_source, clock, settings, "mum", "dinner fri?"),
            "lunch": await detect(socket, message_source, clock, settings, "mum", "lunch sun?"),
            "climb": await detect(socket, message_source, clock, settings, "crew", "climb?"),
        }


async def listed(client: AsyncClient) -> dict[str, dict[str, Any]]:
    return {event["title"]: event for event in (await client.get("/api/events")).json()["events"]}


async def confirm(client: AsyncClient, event: dict[str, Any], **edits: Any) -> dict[str, Any]:
    response = await client.post(f"/api/events/{event['id']}/confirm", json=edits or None)
    assert response.status_code == 200, response.text
    return response.json()


def entry(event: dict[str, Any]) -> dict[str, Any]:
    return {k: event[k] for k in ("id", "title", "start", "allDay")}


async def test_without_a_calendar_entry_in_the_chat_there_is_no_hint(
    running: RunningApp, plans: dict[str, dict[str, Any]]
) -> None:
    assert all(event["existingCalendarEntries"] == [] for event in plans.values())
    assert all(e["existingCalendarEntries"] == [] for e in (await listed(running.client)).values())


async def test_a_plan_from_a_chat_with_an_upcoming_calendar_entry_names_it(
    running: RunningApp, plans: dict[str, dict[str, Any]]
) -> None:
    dinner = await confirm(running.client, plans["dinner"])

    events = await listed(running.client)

    assert events["Sunday lunch"]["existingCalendarEntries"] == [entry(dinner)]
    assert events["Climb"]["existingCalendarEntries"] == []  # another Chat
    assert events["Dinner at Mum's"]["existingCalendarEntries"] == []  # not itself
    # The Anchor Message's banner says so too.
    page = (await running.client.get(f"/api/chats/{dinner['chatId']}/messages")).json()
    [lunch] = [
        e for m in page["messages"] for e in m["detectedEvents"] if e["title"] != dinner["title"]
    ]
    assert lunch["existingCalendarEntries"] == [entry(dinner)]


async def test_a_plan_detected_later_comes_with_the_hint(
    running: RunningApp,
    plans: dict[str, dict[str, Any]],
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    dinner = await confirm(running.client, plans["dinner"])
    plan_model.will_decide(new_plan("Dinner at Mum's", start=days_ahead(3, time(20))))

    async with inbox_socket(running.app) as socket:
        later = await detect(socket, message_source, clock, settings, "mum", "make it 8?")

    assert later["existingCalendarEntries"] == [entry(dinner)]


async def test_confirming_pushes_the_hint_to_the_chats_other_pending_plans(
    running: RunningApp, plans: dict[str, dict[str, Any]]
) -> None:
    async with inbox_socket(running.app) as socket:
        dinner = await confirm(running.client, plans["dinner"])
        pushed = [(await socket.receive_until("EVENT_DETECTED"))["event"] for _ in range(2)]

    assert [event["title"] for event in pushed] == ["Dinner at Mum's", "Sunday lunch"]
    assert pushed[0] == dinner
    assert pushed[1]["existingCalendarEntries"] == [entry(dinner)]
    assert pushed[1] == (await listed(running.client))["Sunday lunch"]


async def test_each_confirmed_plan_names_the_chats_other_calendar_entries(
    running: RunningApp, plans: dict[str, dict[str, Any]]
) -> None:
    lunch = await confirm(running.client, plans["lunch"])
    dinner = await confirm(running.client, plans["dinner"])

    events = await listed(running.client)

    assert events["Sunday lunch"]["existingCalendarEntries"] == [entry(dinner)]
    assert events["Dinner at Mum's"]["existingCalendarEntries"] == [entry(lunch)]


async def test_a_calendar_entry_in_the_past_doesnt_count(
    running: RunningApp, plans: dict[str, dict[str, Any]]
) -> None:
    an_hour_ago = datetime.now(UTC) - timedelta(hours=1)
    await confirm(running.client, plans["dinner"], start=an_hour_ago.isoformat())

    assert (await listed(running.client))["Sunday lunch"]["existingCalendarEntries"] == []


async def test_an_all_day_calendar_entry_counts_until_its_last_day_is_over(
    running: RunningApp, plans: dict[str, dict[str, Any]]
) -> None:
    today = datetime.now(BERLIN).date()
    trip = await confirm(
        running.client,
        plans["dinner"],
        allDay=True,
        start=(today - timedelta(days=2)).isoformat(),
        end=today.isoformat(),
    )

    assert (await listed(running.client))["Sunday lunch"]["existingCalendarEntries"] == [
        entry(trip)
    ]


async def test_an_all_day_calendar_entry_that_ended_yesterday_doesnt_count(
    running: RunningApp, plans: dict[str, dict[str, Any]]
) -> None:
    yesterday = datetime.now(BERLIN).date() - timedelta(days=1)
    await confirm(running.client, plans["dinner"], allDay=True, start=yesterday.isoformat())

    assert (await listed(running.client))["Sunday lunch"]["existingCalendarEntries"] == []
