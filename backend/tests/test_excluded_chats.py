"""Excluded Chats: `PATCH /api/chats/{id} {"excluded": true}` switches plan detection off for a
Chat. It stays in the inbox, but none of its Messages ever reach the Plan Model (ADR-0005)."""

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.adapters.fakes import FakeMessageSource, FakePlanModel
from app.config import Settings
from tests.clock import FakeClock
from tests.conftest import RunningApp, StartRunningApp
from tests.plans import days_ahead, new_plan, texts_sent
from tests.sources import a_chat, a_message
from tests.ws import WebSocketSession, inbox_socket


@pytest.fixture
async def running(
    start_running_app: StartRunningApp, message_source: FakeMessageSource
) -> RunningApp:
    message_source.add_chat(a_chat("work", title="Work"), [a_message("w0", text="hi team")])
    message_source.add_chat(a_chat("ana", title="Ana"), [a_message("a0", text="hey")])
    return await start_running_app()


async def chat(client: AsyncClient, title: str) -> dict[str, Any]:
    chats = (await client.get("/api/chats")).json()["chats"]
    return next(c for c in chats if c["title"] == title)


async def set_excluded(client: AsyncClient, chat_id: int, excluded: bool) -> dict[str, Any]:
    response = await client.patch(f"/api/chats/{chat_id}", json={"excluded": excluded})
    assert response.status_code == 200, response.text
    return response.json()


async def arrive(socket: WebSocketSession, source: FakeMessageSource, chat: str, text: str) -> None:
    number = len(source.messages[chat])
    source.receive(chat, a_message(f"{chat}-{number}", text=text, ago=timedelta(seconds=1)))
    await socket.receive_until("NEW_MESSAGE")


async def detected_in(
    socket: WebSocketSession,
    source: FakeMessageSource,
    clock: FakeClock,
    settings: Settings,
    chat: str,
    text: str,
) -> dict[str, Any]:
    """A plan Message in `chat` is checked: proof that earlier checks have had their turn."""
    await arrive(socket, source, chat, text)
    clock.advance(settings.plan_settle_seconds)
    return await socket.receive_until("EVENT_DETECTED")


async def test_a_chat_can_be_excluded_and_included_again(running: RunningApp) -> None:
    work = await chat(running.client, "Work")
    assert work["excluded"] is False

    excluded = await set_excluded(running.client, work["id"], True)
    listed = await chat(running.client, "Work")
    included = await set_excluded(running.client, work["id"], False)

    assert excluded == {**work, "excluded": True}
    assert listed == excluded
    assert included == work
    assert (await chat(running.client, "Work"))["excluded"] is False


async def test_excluding_an_unknown_chat_is_not_found(running: RunningApp) -> None:
    response = await running.client.patch("/api/chats/9999", json={"excluded": True})

    assert response.status_code == 404


@pytest.mark.parametrize("body", [{}, {"excluded": "maybe"}, {"title": "x"}])
async def test_a_chat_update_needs_excluded(running: RunningApp, body: dict[str, Any]) -> None:
    work = await chat(running.client, "Work")

    response = await running.client.patch(f"/api/chats/{work['id']}", json=body)

    assert response.status_code == 422


async def test_messages_in_an_excluded_chat_still_arrive_but_never_reach_the_plan_model(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    work = await chat(running.client, "Work")
    await set_excluded(running.client, work["id"], True)
    plan_model.will_decide(new_plan("Lunch with Ana", start=days_ahead(2)))

    async with inbox_socket(running.app) as socket:
        await arrive(socket, message_source, "work", "Offsite dinner Friday 7pm")
        assert clock.sleeping == 0
        clock.advance(settings.plan_settle_seconds)
        await detected_in(socket, message_source, clock, settings, "ana", "lunch tomorrow?")

    assert texts_sent(plan_model) == [["hey", "lunch tomorrow?"]]
    last = (await chat(running.client, "Work"))["lastMessage"]["text"]
    assert last == "Offsite dinner Friday 7pm"  # still in the inbox


async def test_detection_scheduled_before_a_chat_was_excluded_never_sends_it(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    work = await chat(running.client, "Work")
    plan_model.will_decide(new_plan("Lunch with Ana", start=days_ahead(2)))

    async with inbox_socket(running.app) as socket:
        await arrive(socket, message_source, "work", "Offsite dinner Friday 7pm")
        assert clock.sleeping == 1  # waiting for the Chat to settle
        await set_excluded(running.client, work["id"], True)
        clock.advance(settings.plan_settle_seconds)
        await detected_in(socket, message_source, clock, settings, "ana", "lunch tomorrow?")

    assert texts_sent(plan_model) == [["hey", "lunch tomorrow?"]]


async def test_a_pending_plan_in_an_excluded_chat_is_not_updated_by_later_messages(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    plan_model.will_decide(new_plan("Offsite", start=days_ahead(3)))
    async with inbox_socket(running.app) as socket:
        await detected_in(socket, message_source, clock, settings, "work", "offsite friday?")
        work = await chat(running.client, "Work")
        await set_excluded(running.client, work["id"], True)
        await arrive(socket, message_source, "work", "actually make it 8")
        assert clock.sleeping == 0

    assert len(plan_model.calls) == 1


async def test_including_a_chat_again_never_checks_what_arrived_while_it_was_excluded(
    running: RunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    work = await chat(running.client, "Work")
    await set_excluded(running.client, work["id"], True)
    plan_model.will_decide(new_plan("Team lunch", start=days_ahead(2)))

    async with inbox_socket(running.app) as socket:
        await arrive(socket, message_source, "work", "Offsite dinner Friday 7pm")
        await arrive(socket, message_source, "work", "(confidential) board meeting monday")
        await set_excluded(running.client, work["id"], False)
        assert clock.sleeping == 0
        clock.advance(settings.plan_settle_seconds)
        await detected_in(socket, message_source, clock, settings, "work", "team lunch thu?")

    # The Messages from while it was excluded aren't sent even as context.
    assert texts_sent(plan_model) == [["hi team", "team lunch thu?"]]
