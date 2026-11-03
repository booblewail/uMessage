"""Plan detection: a new Message that might be about a plan has its Chat checked by the Plan
Model once the Chat has settled (no new Message for `PLAN_SETTLE_SECONDS`); the decision
becomes, or revises, a Pending Review Detected Event shown beneath its Anchor Message and
pushed over `/ws` as `EVENT_DETECTED`.

The settle delay runs on a fake clock (`clock.advance`), so nothing here waits for real.
"""

import logging
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from asgi_lifespan import LifespanManager
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine

from app.adapters.fakes import FakeCalendar, FakeMessageSource, FakePlanModel
from app.adapters.protocols import NoPlan, PendingPlan, PlanWindowMessage
from app.config import Settings
from app.main import build_app, create_app
from app.models import DetectedEvent, DetectedEventStatus
from tests.clock import FakeClock
from tests.conftest import (
    RETRY_SECONDS,
    RunningApp,
    StartRunningApp,
    eventually,
    http_client,
    make_settings,
    wait_for_first_import,
)
from tests.plans import days_ahead, new_plan, texts_sent, update_plan
from tests.sources import a_chat, a_message, messages_minutes_apart
from tests.ws import WebSocketSession, inbox_socket

SYDNEY = ZoneInfo("Australia/Sydney")


@pytest.fixture
def settings(database_url: str) -> Settings:
    return make_settings(database_url, user_timezone="Australia/Sydney")


async def chat_id(client: AsyncClient, title: str) -> int:
    chats = (await client.get("/api/chats")).json()["chats"]
    return next(chat["id"] for chat in chats if chat["title"] == title)


async def thread(client: AsyncClient, chat: int) -> list[dict[str, Any]]:
    url = f"/api/chats/{chat}/messages"
    return (await client.get(url, params={"limit": 200})).json()["messages"]


async def events(client: AsyncClient, **params: object) -> list[dict[str, Any]]:
    response = await client.get("/api/events", params=params)
    assert response.status_code == 200, response.text
    return response.json()["events"]


def utc_iso(local: datetime) -> str:
    """How the API shows a local wall time in the user's time zone: in UTC."""
    return local.replace(tzinfo=SYDNEY).astimezone(UTC).isoformat().replace("+00:00", "Z")


def as_instant(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


async def arrive(
    socket: WebSocketSession, source: FakeMessageSource, chat: str, *texts: str, **kw: Any
) -> list[dict[str, Any]]:
    """Messages arrive in a Chat one after another; returns them as pushed to the inbox."""
    pushed = []
    for number, text in enumerate(texts):
        outbound = text.startswith("> ")
        source.receive(
            chat,
            a_message(
                f"{chat}-live-{len(source.messages[chat])}",
                text=text.removeprefix("> "),
                outbound=outbound,
                ago=kw.get("ago", timedelta(seconds=len(texts) - number)),
            ),
        )
        pushed.append((await socket.receive_until("NEW_MESSAGE"))["message"])
    return pushed


@pytest.fixture
async def running(
    start_running_app: StartRunningApp, message_source: FakeMessageSource
) -> RunningApp:
    message_source.add_chat(
        a_chat("wa-ana", title="Ana", active_ago=timedelta(hours=1)),
        [a_message("old-1", text="hey you", ago=timedelta(hours=1))],
    )
    message_source.add_chat(
        a_chat("wa-crew", title="Crew", active_ago=timedelta(hours=2)),
        [a_message("old-2", text="yo", ago=timedelta(hours=2))],
    )
    return await start_running_app()


async def test_a_plan_made_over_several_messages_is_one_detected_event_on_the_last_one(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    friday = days_ahead(3, time(19, 30))
    plan_model.will_decide(new_plan("Dinner at Chaco Bar", start=friday, location="Chaco Bar"))

    async with inbox_socket(running.app) as socket:
        pushed = await arrive(
            socket, message_source, "wa-ana", "Dinner Friday?", "> Keen", "7:30pm at Chaco Bar"
        )
        clock.advance(settings.plan_settle_seconds)
        detected = await socket.receive_until("EVENT_DETECTED")

    [call] = plan_model.calls
    assert call.messages == [
        PlanWindowMessage("Ana", "hey you", call.messages[0].sent_at, outbound=False),
        PlanWindowMessage("Ana", "Dinner Friday?", call.messages[1].sent_at, outbound=False),
        PlanWindowMessage("You", "Keen", call.messages[2].sent_at, outbound=True),
        PlanWindowMessage("Ana", "7:30pm at Chaco Bar", call.messages[3].sent_at, outbound=False),
    ]
    assert [m.sent_at for m in call.messages[1:]] == [as_instant(p["sentAt"]) for p in pushed]
    assert (call.pending, call.timezone) == ([], "Australia/Sydney")
    assert abs(call.now - datetime.now(UTC)) < timedelta(seconds=10)

    ana = await chat_id(running.client, "Ana")
    event = detected["event"]
    assert detected == {"type": "EVENT_DETECTED", "change": "created", "event": event}
    assert {key: value for key, value in event.items() if key not in ("id", "createdAt")} == {
        "chatId": ana,
        "chat": {"id": ana, "title": "Ana", "platform": "whatsapp"},
        "anchorMessageId": pushed[-1]["id"],
        "anchorMessage": {
            key: pushed[-1][key] for key in ("id", "senderName", "text", "sentAt", "outbound")
        },
        "title": "Dinner at Chaco Bar",
        "start": utc_iso(friday),
        "end": None,
        "allDay": False,
        "location": "Chaco Bar",
        "confidence": 0.9,
        "status": "pending_review",
        "calendarEntryId": None,
        "existingCalendarEntries": [],
        "updatedAt": event["createdAt"],
    }
    assert await events(running.client) == [event]
    messages = await thread(running.client, ana)
    assert [m["detectedEvents"] for m in messages] == [[], [], [], [event]]


async def test_each_new_message_restarts_the_settle_delay(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    settle = settings.plan_settle_seconds
    plan_model.will_decide(new_plan(start=days_ahead(3)))

    async with inbox_socket(running.app) as socket:
        await arrive(socket, message_source, "wa-ana", "Dinner Friday?")
        clock.advance(settle * 2 / 3)
        await arrive(socket, message_source, "wa-ana", "> Keen")  # no plan words, still counts
        clock.advance(settle * 2 / 3)  # past the first Message's delay, not the second's
        assert clock.sleeping == 1
        clock.advance(settle / 3)
        await socket.receive_until("EVENT_DETECTED")

    assert texts_sent(plan_model) == [["hey you", "Dinner Friday?", "Keen"]]
    assert clock.sleeping == 0


async def test_the_plan_model_reads_the_last_five_messages_of_the_chat(
    start_running_app: StartRunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    message_source.add_chat(a_chat("wa-1", title="Busy"), messages_minutes_apart("m", 8))
    running = await start_running_app()

    async with inbox_socket(running.app) as socket:
        await arrive(socket, message_source, "wa-1", "drinks tonight?")
        clock.advance(settings.plan_settle_seconds)
        await eventually(lambda: _called(plan_model))

    assert texts_sent(plan_model) == [
        ["Message m-5", "Message m-6", "Message m-7", "Message m-8", "drinks tonight?"]
    ]


async def _called(plan_model: FakePlanModel, times: int = 1) -> bool | None:
    return True if len(plan_model.calls) >= times else None


async def detect_one(
    running: RunningApp,
    socket: WebSocketSession,
    source: FakeMessageSource,
    clock: FakeClock,
    settings: Settings,
    chat: str,
    *texts: str,
) -> dict[str, Any]:
    """Messages arrive, the Chat settles, and the next EVENT_DETECTED is returned."""
    await arrive(socket, source, chat, *texts)
    clock.advance(settings.plan_settle_seconds)
    return await socket.receive_until("EVENT_DETECTED")


async def test_a_change_to_the_plan_updates_its_detected_event_and_moves_its_anchor(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    friday = days_ahead(3, time(19, 30))
    plan_model.will_decide(new_plan("Dinner at Chaco Bar", start=friday, location="Chaco Bar"))
    async with inbox_socket(running.app) as socket:
        first = await detect_one(
            running, socket, message_source, clock, settings, "wa-ana", "Dinner Friday 7:30pm?"
        )
        event_id = first["event"]["id"]
        later = friday.replace(hour=20, minute=0)
        plan_model.will_decide(
            update_plan(event_id, "Dinner at Chaco Bar", start=later, location="Chaco Bar")
        )
        # No plan words: a Chat with a Pending Review Detected Event is checked on any Message.
        [moved] = await arrive(socket, message_source, "wa-ana", "actually make it 8")
        clock.advance(settings.plan_settle_seconds)
        updated = await socket.receive_until("EVENT_DETECTED")

    assert plan_model.calls[1].pending == [
        PendingPlan(
            id=event_id,
            title="Dinner at Chaco Bar",
            start=friday.replace(tzinfo=SYDNEY).astimezone(UTC),
            end=None,
            all_day=False,
            location="Chaco Bar",
        )
    ]
    assert updated["change"] == "updated"
    event = updated["event"]
    assert (event["id"], event["start"], event["anchorMessageId"]) == (
        event_id,
        utc_iso(later),
        moved["id"],
    )
    assert event["createdAt"] == first["event"]["createdAt"]
    assert as_instant(event["updatedAt"]) > as_instant(first["event"]["updatedAt"])
    assert await events(running.client) == [event]
    anchored = {
        m["text"]: m["detectedEvents"]
        for m in await thread(running.client, event["chatId"])
        if m["detectedEvents"]
    }
    assert anchored == {"actually make it 8": [event]}


async def test_a_second_plan_in_the_same_chat_is_a_separate_detected_event(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    plan_model.will_decide(
        new_plan("Dinner", start=days_ahead(3)),
        new_plan("Lunch", start=days_ahead(2, time(13))),
    )
    async with inbox_socket(running.app) as socket:
        dinner = await detect_one(
            running, socket, message_source, clock, settings, "wa-ana", "Dinner Friday?"
        )
        lunch = await detect_one(
            running, socket, message_source, clock, settings, "wa-ana", "also lunch Thursday?"
        )

    assert [plan.id for plan in plan_model.calls[1].pending] == [dinner["event"]["id"]]
    assert lunch["change"] == "created"
    assert [e["title"] for e in await events(running.client)] == ["Lunch", "Dinner"]  # by start


async def test_an_all_day_plan_keeps_its_date(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    saturday = days_ahead(4, time(0))
    plan_model.will_decide(new_plan("Beach day", start=saturday, all_day=True))
    async with inbox_socket(running.app) as socket:
        detected = await detect_one(
            running, socket, message_source, clock, settings, "wa-ana", "beach saturday?"
        )

    event = detected["event"]
    assert (event["allDay"], event["start"], event["end"]) == (True, utc_iso(saturday), None)


async def test_an_offset_aware_time_from_the_plan_model_is_stored_as_that_instant(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    start = days_ahead(3, time(19)).replace(tzinfo=ZoneInfo("Europe/London"))
    plan_model.will_decide(new_plan(start=start, end=start + timedelta(hours=2)))
    async with inbox_socket(running.app) as socket:
        detected = await detect_one(
            running, socket, message_source, clock, settings, "wa-ana", "call friday 7pm UK?"
        )

    event = detected["event"]
    assert (as_instant(event["start"]), as_instant(event["end"])) == (
        start,
        start + timedelta(hours=2),
    )


@pytest.mark.parametrize(
    "decision",
    [
        pytest.param(new_plan(start=days_ahead(3), confidence=0.49), id="not-confident-enough"),
        pytest.param(new_plan(start=days_ahead(-1)), id="already-started"),
        pytest.param(new_plan(start=days_ahead(-1, time(0)), all_day=True), id="day-has-passed"),
        pytest.param(NoPlan(), id="no-plan"),
    ],
)
async def test_some_decisions_create_nothing(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
    decision: object,
) -> None:
    plan_model.will_decide(decision, new_plan("Next one", start=days_ahead(5)))  # type: ignore[arg-type]
    async with inbox_socket(running.app) as socket:
        await arrive(socket, message_source, "wa-ana", "dinner yesterday was fun")
        clock.advance(settings.plan_settle_seconds)
        # A later check of the same Chat runs after this one has finished.
        detected = await detect_one(
            running, socket, message_source, clock, settings, "wa-ana", "lunch next week?"
        )

    assert len(plan_model.calls) == 2
    assert [e["title"] for e in await events(running.client)] == ["Next one"]
    assert detected["event"]["title"] == "Next one"


async def test_a_plan_from_today_counts_until_its_day_is_over(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    today = datetime.now(SYDNEY).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    plan_model.will_decide(new_plan("Market day", start=today, all_day=True))
    async with inbox_socket(running.app) as socket:
        detected = await detect_one(
            running, socket, message_source, clock, settings, "wa-ana", "market today?"
        )

    assert detected["event"]["title"] == "Market day"


async def mark_confirmed(settings: Settings, event_id: int) -> None:
    """Confirm a Detected Event in the database (until #9 adds confirming to the API)."""
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                update(DetectedEvent)
                .where(DetectedEvent.id == event_id)
                .values(status=DetectedEventStatus.CONFIRMED)
            )
    finally:
        await engine.dispose()


@pytest.mark.parametrize("named", ["dismissed", "confirmed", "other-chat", "unknown"])
async def test_an_update_to_a_detected_event_that_isnt_pending_in_the_chat_is_ignored(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
    named: str,
) -> None:
    plan_model.will_decide(new_plan("Ana's plan", start=days_ahead(3)))
    plan_model.will_decide(new_plan("Crew's plan", start=days_ahead(4)))
    async with inbox_socket(running.app) as socket:
        ana = await detect_one(
            running, socket, message_source, clock, settings, "wa-ana", "dinner fri?"
        )
        crew = await detect_one(
            running, socket, message_source, clock, settings, "wa-crew", "climb sat?"
        )
        ana_id, crew_id = ana["event"]["id"], crew["event"]["id"]
        if named == "dismissed":
            assert (await running.client.post(f"/api/events/{ana_id}/dismiss")).status_code == 200
            await socket.receive_until("EVENT_DETECTED")
        elif named == "confirmed":
            await mark_confirmed(settings, ana_id)
        target = {"dismissed": ana_id, "confirmed": ana_id, "other-chat": crew_id}.get(named, 999)
        before = await events(running.client)
        plan_model.will_decide(
            update_plan(target, "Hijacked", start=days_ahead(6)),
            new_plan("Barrier", start=days_ahead(9)),
        )
        await arrive(socket, message_source, "wa-ana", "dinner sat instead?")
        clock.advance(settings.plan_settle_seconds)
        await detect_one(running, socket, message_source, clock, settings, "wa-ana", "lunch?")

    after = [e for e in await events(running.client) if e["title"] != "Barrier"]
    assert after == before
    if named in ("dismissed", "confirmed"):
        assert plan_model.calls[2].pending == []  # never offered as a pending plan


async def test_first_import_messages_are_never_checked(
    start_running_app: StartRunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    message_source.add_chat(
        a_chat("wa-1", title="Imported"),
        [a_message("i1", text="Dinner Friday 7pm at Chaco?"), a_message("i2", text="yes!")],
    )
    running = await start_running_app()

    assert clock.sleeping == 0
    clock.advance(settings.plan_settle_seconds)
    async with inbox_socket(running.app) as socket:
        await arrive(socket, message_source, "wa-1", "brunch sunday?")
        clock.advance(settings.plan_settle_seconds)
        await eventually(lambda: _called(plan_model))

    # The imported Messages are context for the new one, but never checked on their own.
    assert texts_sent(plan_model) == [["Dinner Friday 7pm at Chaco?", "yes!", "brunch sunday?"]]


async def test_messages_that_arrive_late_with_old_timestamps_are_still_checked(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    # e.g. the laptop slept: Messages sent hours ago only arrive now.
    plan_model.will_decide(new_plan("Dinner", start=days_ahead(3)))
    async with inbox_socket(running.app) as socket:
        late = timedelta(minutes=40)  # older than when it arrives, newer than "hey you"
        await arrive(socket, message_source, "wa-ana", "dinner friday?", ago=late)
        clock.advance(settings.plan_settle_seconds)
        detected = await socket.receive_until("EVENT_DETECTED")

    assert texts_sent(plan_model) == [["hey you", "dinner friday?"]]
    assert detected["event"]["title"] == "Dinner"


async def test_scrolled_back_history_is_never_checked(
    start_running_app: StartRunningApp,
    message_source: FakeMessageSource,
    clock: FakeClock,
) -> None:
    # First Import keeps the newest 50; the older ones (with plan words) come from scrolling.
    older = [a_message(f"o{n}", text=f"dinner friday {n}pm?", ago=timedelta(days=3)) for n in "12"]
    message_source.add_chat(a_chat("wa-1"), [*older, *messages_minutes_apart("m", 50)])
    running = await start_running_app()
    chat = await chat_id(running.client, "Chat wa-1")
    first = (await running.client.get(f"/api/chats/{chat}/messages")).json()

    page = await running.client.get(
        f"/api/chats/{chat}/messages", params={"before": first["olderCursor"]}
    )

    assert [m["text"] for m in page.json()["messages"]] == [
        "dinner friday 1pm?",
        "dinner friday 2pm?",
    ]
    assert clock.sleeping == 0


async def test_a_reply_sent_from_the_inbox_is_checked_too(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    ana = await chat_id(running.client, "Ana")
    async with inbox_socket(running.app) as socket:
        sent = await running.client.post(
            f"/api/chats/{ana}/messages", json={"text": "Dinner Friday at 7:30?"}
        )
        assert sent.status_code == 201
        await socket.receive_until("NEW_MESSAGE")
        clock.advance(settings.plan_settle_seconds)
        await eventually(lambda: _called(plan_model))

    [call] = plan_model.calls
    assert (call.messages[-1].text, call.messages[-1].outbound) == ("Dinner Friday at 7:30?", True)


async def test_a_plan_model_failure_is_logged_and_messages_keep_arriving(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    plan_model.will_decide(RuntimeError("Gemini is down"), new_plan(start=days_ahead(3)))
    caplog.set_level(logging.WARNING)
    async with inbox_socket(running.app) as socket:
        await arrive(socket, message_source, "wa-ana", "dinner friday?")
        clock.advance(settings.plan_settle_seconds)
        await eventually(lambda: _called(plan_model))
        await arrive(socket, message_source, "wa-ana", "still on for dinner?", "> yes")
        clock.advance(settings.plan_settle_seconds)
        detected = await socket.receive_until("EVENT_DETECTED")

    assert detected["change"] == "created"
    assert "Gemini is down" in caplog.text
    status = (await running.client.get("/api/status")).json()["planDetection"]
    assert status == {"enabled": True, "reason": None, "lastError": None}


async def test_plan_model_calls_at_the_same_time_are_capped(
    start_running_app: StartRunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    assert settings.plan_max_concurrent == 2
    for name in "abc":
        message_source.add_chat(a_chat(name), [a_message(f"{name}0")])
    running = await start_running_app()
    plan_model.answering.clear()

    async with inbox_socket(running.app) as socket:
        for name in "abc":
            await arrive(socket, message_source, name, "dinner tonight?")
        clock.advance(settings.plan_settle_seconds)
        await eventually(lambda: _called(plan_model, times=2))
        assert plan_model.in_flight == 2
        plan_model.answering.set()
        await eventually(lambda: _called(plan_model, times=3))

    assert plan_model.most_in_flight == 2


async def test_without_a_plan_model_detection_is_off_and_messages_still_arrive(
    settings: Settings, message_source: FakeMessageSource, clock: FakeClock
) -> None:
    message_source.add_chat(a_chat("wa-1"), [a_message("m1")])
    app = create_app(
        settings,
        message_source=message_source,
        plan_model=None,
        calendar=FakeCalendar(),
        retry_seconds=RETRY_SECONDS,
        settle_sleep=clock.sleep,
    )
    async with LifespanManager(app) as manager, http_client(manager.app) as client:
        await wait_for_first_import(client)
        async with inbox_socket(manager.app) as socket:
            await arrive(socket, message_source, "wa-1", "dinner friday?")
        status = (await client.get("/api/status")).json()["planDetection"]

    assert status["enabled"] is False
    assert status["reason"]
    assert clock.sleeping == 0


async def test_real_mode_without_a_gemini_api_key_starts_with_detection_off(
    database_url: str,
) -> None:
    settings = make_settings(
        database_url, umessage_mode="real", gemini_api_key="", beeper_api_url="http://127.0.0.1:9"
    )
    async with LifespanManager(build_app(settings)) as manager, http_client(manager.app) as client:
        status = (await client.get("/api/status")).json()["planDetection"]

    assert status["enabled"] is False
    assert "GEMINI_API_KEY" in status["reason"]


async def test_real_mode_with_a_gemini_api_key_has_detection_on(database_url: str) -> None:
    settings = make_settings(
        database_url,
        umessage_mode="real",
        gemini_api_key="k" * 20,
        beeper_api_url="http://127.0.0.1:9",
    )

    async with LifespanManager(build_app(settings)) as manager, http_client(manager.app) as client:
        status = (await client.get("/api/status")).json()["planDetection"]

    assert status == {"enabled": True, "reason": None, "lastError": None}
