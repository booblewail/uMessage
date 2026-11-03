"""`GET /api/events` lists Detected Events (by start), each with its Chat and Anchor Message;
`POST /api/events/{id}/dismiss` turns a Pending Review one Dismissed and pushes the change as
`EVENT_DETECTED`."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.adapters.fakes import FakeMessageSource, FakePlanModel
from app.adapters.protocols import Platform
from app.config import Settings
from tests.clock import FakeClock
from tests.conftest import RunningApp, StartRunningApp
from tests.plans import days_ahead, detect, new_plan
from tests.sources import a_chat, a_message
from tests.ws import inbox_socket


@pytest.fixture
async def running(
    start_running_app: StartRunningApp, message_source: FakeMessageSource
) -> RunningApp:
    message_source.add_chat(a_chat("ana", title="Ana"), [a_message("a0")])
    message_source.add_chat(
        a_chat("crew", title="Crew", platform=Platform.DISCORD), [a_message("c0")]
    )
    return await start_running_app()


@pytest.fixture
async def three_events(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> list[dict[str, Any]]:
    """Ana's dinner (in 3 days) and lunch (in 1), Crew's climb (in 2)."""
    plan_model.will_decide(
        new_plan("Dinner", start=days_ahead(3)),
        new_plan("Lunch", start=days_ahead(1, time(13))),
        new_plan("Climb", start=days_ahead(2)),
    )
    async with inbox_socket(running.app) as socket:
        return [
            await detect(socket, message_source, clock, settings, "ana", "dinner fri?"),
            await detect(socket, message_source, clock, settings, "ana", "lunch thu?"),
            await detect(socket, message_source, clock, settings, "crew", "climb wed?"),
        ]


async def titles(client: AsyncClient, **params: object) -> list[str]:
    response = await client.get("/api/events", params=params)
    assert response.status_code == 200, response.text
    return [event["title"] for event in response.json()["events"]]


async def test_detected_events_are_listed_by_start(
    running: RunningApp, three_events: list[dict[str, Any]]
) -> None:
    assert await titles(running.client) == ["Lunch", "Climb", "Dinner"]


async def test_detected_events_can_be_listed_for_one_chat_and_status(
    running: RunningApp, three_events: list[dict[str, Any]]
) -> None:
    dinner, _lunch, climb = three_events
    await running.client.post(f"/api/events/{dinner['id']}/dismiss")

    assert await titles(running.client, chatId=dinner["chatId"]) == ["Lunch", "Dinner"]
    assert await titles(running.client, chatId=climb["chatId"]) == ["Climb"]
    assert await titles(running.client, status="pending_review") == ["Lunch", "Climb"]
    assert await titles(running.client, status="dismissed") == ["Dinner"]
    assert await titles(running.client, status="dismissed", chatId=climb["chatId"]) == []


async def test_each_detected_event_names_its_chat_and_quotes_its_anchor_message(
    running: RunningApp, three_events: list[dict[str, Any]]
) -> None:
    events = (await running.client.get("/api/events")).json()["events"]
    climb = next(event for event in events if event["title"] == "Climb")

    assert climb["chat"] == {"id": climb["chatId"], "title": "Crew", "platform": "discord"}
    anchor = climb["anchorMessage"]
    assert anchor == {
        "id": climb["anchorMessageId"],
        "senderName": "Ana",
        "text": "climb wed?",
        "sentAt": anchor["sentAt"],
        "outbound": False,
    }
    assert datetime.fromisoformat(anchor["sentAt"]) <= datetime.now(UTC)
    # What was pushed when it was detected is what the list shows.
    assert three_events[2] == climb


async def test_several_statuses_can_be_listed_at_once(
    running: RunningApp, three_events: list[dict[str, Any]]
) -> None:
    dinner, lunch, _climb = three_events
    await running.client.post(f"/api/events/{dinner['id']}/dismiss")
    await running.client.post(f"/api/events/{lunch['id']}/confirm")

    repeated = await titles(running.client, status=["confirmed", "dismissed"])
    comma_separated = await titles(running.client, status="confirmed,dismissed")
    spaced = await titles(running.client, status="pending_review, confirmed")

    assert repeated == comma_separated == ["Lunch", "Dinner"]
    assert spaced == ["Lunch", "Climb"]


async def test_events_can_be_listed_from_a_time_on(
    running: RunningApp, three_events: list[dict[str, Any]]
) -> None:
    day_after_tomorrow = datetime.combine(date.today() + timedelta(days=2), time(), tzinfo=UTC)

    assert await titles(running.client, **{"from": day_after_tomorrow.isoformat()}) == [
        "Climb",
        "Dinner",
    ]
    assert await titles(running.client, **{"from": three_events[0]["start"]}) == ["Dinner"]
    assert await titles(running.client, **{"from": "2000-01-01"}) == ["Lunch", "Climb", "Dinner"]


async def test_an_invalid_from_is_rejected(running: RunningApp) -> None:
    response = await running.client.get("/api/events", params={"from": "next week"})

    assert response.status_code == 422


async def test_dismissing_a_pending_detected_event_pushes_the_change(
    running: RunningApp, three_events: list[dict[str, Any]]
) -> None:
    dinner = three_events[0]

    async with inbox_socket(running.app) as socket:
        response = await running.client.post(f"/api/events/{dinner['id']}/dismiss")
        pushed = await socket.receive_until("EVENT_DETECTED")

    assert response.status_code == 200
    dismissed = response.json()
    assert dismissed == {**dinner, "status": "dismissed", "updatedAt": dismissed["updatedAt"]}
    assert pushed == {"type": "EVENT_DETECTED", "change": "updated", "event": dismissed}
    # The Anchor Message still lists it (the inbox shows only Pending Review and Confirmed).
    page = (await running.client.get(f"/api/chats/{dinner['chatId']}/messages")).json()
    anchor = next(m for m in page["messages"] if m["id"] == dinner["anchorMessageId"])
    assert anchor["detectedEvents"] == [dismissed]


async def test_dismissing_twice_is_a_conflict(
    running: RunningApp, three_events: list[dict[str, Any]]
) -> None:
    url = f"/api/events/{three_events[0]['id']}/dismiss"
    await running.client.post(url)

    response = await running.client.post(url)

    assert response.status_code == 409
    assert "dismissed" in response.json()["detail"]


async def test_dismissing_an_unknown_detected_event_is_not_found(running: RunningApp) -> None:
    response = await running.client.post("/api/events/12345/dismiss")

    assert response.status_code == 404


@pytest.mark.parametrize("status", ["maybe", "confirmed,maybe", ","])
async def test_an_invalid_status_filter_is_rejected(running: RunningApp, status: str) -> None:
    response = await running.client.get("/api/events", params={"status": status})

    assert response.status_code == 422


async def test_the_events_api_needs_the_api_token(anonymous_client: AsyncClient) -> None:
    listed = await anonymous_client.get("/api/events")
    dismissed = await anonymous_client.post("/api/events/1/dismiss")

    assert (listed.status_code, dismissed.status_code) == (401, 401)
