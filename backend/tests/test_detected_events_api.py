"""`GET /api/events` lists Detected Events (by start); `POST /api/events/{id}/dismiss` turns a
Pending Review one Dismissed and pushes the change as `EVENT_DETECTED`."""

from datetime import time, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.adapters.fakes import FakeMessageSource, FakePlanModel
from app.config import Settings
from tests.clock import FakeClock
from tests.conftest import RunningApp, StartRunningApp
from tests.plans import days_ahead, new_plan
from tests.sources import a_chat, a_message
from tests.ws import WebSocketSession, inbox_socket


async def detect(
    socket: WebSocketSession,
    source: FakeMessageSource,
    clock: FakeClock,
    settings: Settings,
    chat: str,
    text: str,
) -> dict[str, Any]:
    source.receive(chat, a_message(f"{chat}-{text}", text=text, ago=timedelta(seconds=1)))
    await socket.receive_until("NEW_MESSAGE")
    clock.advance(settings.plan_settle_seconds)
    return (await socket.receive_until("EVENT_DETECTED"))["event"]


@pytest.fixture
async def running(
    start_running_app: StartRunningApp, message_source: FakeMessageSource
) -> RunningApp:
    message_source.add_chat(a_chat("ana", title="Ana"), [a_message("a0")])
    message_source.add_chat(a_chat("crew", title="Crew"), [a_message("c0")])
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


async def test_an_invalid_status_filter_is_rejected(running: RunningApp) -> None:
    response = await running.client.get("/api/events", params={"status": "maybe"})

    assert response.status_code == 422


async def test_the_events_api_needs_the_api_token(anonymous_client: AsyncClient) -> None:
    listed = await anonymous_client.get("/api/events")
    dismissed = await anonymous_client.post("/api/events/1/dismiss")

    assert (listed.status_code, dismissed.status_code) == (401, 401)
