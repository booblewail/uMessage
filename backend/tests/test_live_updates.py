"""New Messages appear live: after First Import, new Messages are fetched from Beeper Desktop,
stored once, and pushed to the inbox over `/ws` as `NEW_MESSAGE`."""

from datetime import timedelta

import pytest
from asgi_lifespan import LifespanManager
from httpx import AsyncClient

from app.adapters.fakes import FakeMessageSource
from app.adapters.protocols import ChatKind, Platform
from app.config import Settings
from tests.conftest import (
    RunningApp,
    StartRunningApp,
    eventually,
    http_client,
    make_app,
    wait_for_first_import,
)
from tests.sources import a_chat, a_message
from tests.ws import WebSocketRejectedError, inbox_socket


async def chats(client: AsyncClient) -> list[dict]:
    return (await client.get("/api/chats")).json()["chats"]


async def thread(client: AsyncClient, chat_id: int) -> list[dict]:
    page = (await client.get(f"/api/chats/{chat_id}/messages", params={"limit": 200})).json()
    return page["messages"]


async def texts_by_chat(client: AsyncClient) -> dict[str, list[str]]:
    return {
        chat["title"]: [message["text"] for message in await thread(client, chat["id"])]
        for chat in await chats(client)
    }


async def test_a_new_message_is_pushed_to_the_inbox_as_it_is_stored(
    start_running_app: StartRunningApp, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1", title="Climbing crew"), [a_message("m1")])
    running = await start_running_app()

    async with inbox_socket(running.app) as socket:
        message_source.receive("wa-1", a_message("m2", sender="Lea", text="Running late!"))
        event = await socket.receive_until("NEW_MESSAGE")

    [chat] = await chats(running.client)
    stored = (await thread(running.client, chat["id"]))[-1]
    assert event == {"type": "NEW_MESSAGE", "chatId": chat["id"], "message": stored, "chat": chat}
    assert (stored["senderName"], stored["text"], stored["outbound"]) == (
        "Lea",
        "Running late!",
        False,
    )
    assert chat["lastMessage"]["text"] == "Running late!"


async def test_a_new_message_moves_its_chat_to_the_top(
    start_running_app: StartRunningApp, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(
        a_chat("recent", title="Recent", active_ago=timedelta(minutes=1)),
        [a_message("r1", ago=timedelta(minutes=1))],
    )
    message_source.add_chat(
        a_chat("quiet", title="Quiet", active_ago=timedelta(days=2)),
        [a_message("q1", ago=timedelta(days=2))],
    )
    running = await start_running_app()
    before = [chat["title"] for chat in await chats(running.client)]

    async with inbox_socket(running.app) as socket:
        message_source.receive("quiet", a_message("q2", ago=timedelta(0), text="Hello again"))
        event = await socket.receive_until("NEW_MESSAGE")

    after = [chat["title"] for chat in await chats(running.client)]
    assert (before, after) == (["Recent", "Quiet"], ["Quiet", "Recent"])
    assert event["chat"]["title"] == "Quiet"


async def test_a_new_message_reported_more_than_once_is_stored_and_pushed_once(
    start_running_app: StartRunningApp, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1", title="Chat"), [a_message("m1", text="Old")])
    running = await start_running_app()
    repeated = a_message("m2", text="Twice?", ago=timedelta(0))

    async with inbox_socket(running.app) as socket:
        message_source.receive("wa-1", repeated)
        message_source.receive("wa-1", repeated)
        message_source.receive("wa-1", a_message("m3", text="Next", ago=timedelta(0)))
        pushed = [(await socket.receive_until("NEW_MESSAGE"))["message"]["text"] for _ in "ab"]

    assert pushed == ["Twice?", "Next"]
    assert await texts_by_chat(running.client) == {"Chat": ["Old", "Twice?", "Next"]}


async def test_a_new_conversation_appears_as_a_new_chat(
    start_running_app: StartRunningApp, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1", title="Existing"), [a_message("m1")])
    running = await start_running_app()

    async with inbox_socket(running.app) as socket:
        message_source.add_chat(
            a_chat("ig-new", platform=Platform.INSTAGRAM, title="Dana", active_ago=timedelta(0)),
            [a_message("n1", sender="Dana", text="hey! long time", ago=timedelta(0))],
        )
        event = await socket.receive_until("NEW_MESSAGE")

    listed = await chats(running.client)
    assert [chat["title"] for chat in listed] == ["Dana", "Existing"]
    assert event["chat"] == listed[0]
    assert (event["chat"]["platform"], event["message"]["text"]) == ("instagram", "hey! long time")


async def test_new_messages_in_discord_server_channels_are_left_out(
    start_running_app: StartRunningApp, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1", title="Existing"), [a_message("m1")])
    running = await start_running_app()

    async with inbox_socket(running.app) as socket:
        message_source.add_chat(
            a_chat("dc-srv", platform=Platform.DISCORD, kind=ChatKind.SERVER_CHANNEL),
            [a_message("s1", text="@everyone new release", ago=timedelta(0))],
        )
        message_source.receive("wa-1", a_message("m2", text="After", ago=timedelta(0)))
        event = await socket.receive_until("NEW_MESSAGE")

    assert event["message"]["text"] == "After"
    assert [chat["title"] for chat in await chats(running.client)] == ["Existing"]


async def test_a_message_that_arrives_during_first_import_is_not_lost(
    settings: Settings, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1", title="Chat"), [a_message("m1", text="Before")])
    message_source.messages_readable.clear()

    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            await wait_for_first_import(client, until="running")
            message_source.receive("wa-1", a_message("m2", text="During", ago=timedelta(0)))
            message_source.messages_readable.set()
            await wait_for_first_import(client)
            texts = await eventually(lambda: _texts_once(client, "Chat", ["Before", "During"]))

    assert texts == ["Before", "During"]


async def _texts_once(client: AsyncClient, title: str, expected: list[str]) -> list[str] | None:
    texts = (await texts_by_chat(client)).get(title)
    return texts if texts == expected else None


async def test_messages_missed_while_beeper_desktop_was_unreachable_arrive_once_it_is_back(
    start_running_app: StartRunningApp, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1", title="Chat"), [a_message("m1", text="Before")])
    running = await start_running_app()

    async with inbox_socket(running.app) as socket:
        message_source.running = False  # the laptop sleeps, or Beeper Desktop quits
        message_source.receive("wa-1", a_message("m2", text="While away", ago=timedelta(0)))
        status = (await running.client.get("/api/status")).json()["messageSource"]
        message_source.running = True
        event = await socket.receive_until("NEW_MESSAGE")

    assert status["running"] is False
    assert event["message"]["text"] == "While away"
    assert await texts_by_chat(running.client) == {"Chat": ["Before", "While away"]}


async def test_no_message_is_lost_or_duplicated_across_a_restart(
    settings: Settings, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1", title="Chat"), [a_message("m1", text="Imported")])
    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with inbox_socket(manager.app) as socket, http_client(manager.app) as client:
            await wait_for_first_import(client)
            message_source.receive("wa-1", a_message("m2", text="Live", ago=timedelta(0)))
            await socket.receive_until("NEW_MESSAGE")

    # uMessage is stopped while a Message arrives.
    message_source.receive("wa-1", a_message("m3", text="While stopped", ago=timedelta(0)))
    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            texts = await eventually(
                lambda: _texts_once(client, "Chat", ["Imported", "Live", "While stopped"])
            )

    assert texts == ["Imported", "Live", "While stopped"]


async def test_the_inbox_socket_says_when_it_is_connected(running_app: RunningApp) -> None:
    async with inbox_socket(running_app.app) as socket:
        assert socket is not None  # entering it received {"type": "CONNECTED"}


@pytest.mark.parametrize("token", [None, "", "not-the-token"])
async def test_the_inbox_socket_needs_the_api_token(
    running_app: RunningApp, token: str | None
) -> None:
    with pytest.raises(WebSocketRejectedError) as rejected:
        async with inbox_socket(running_app.app, token=token):
            pass

    assert rejected.value.code == 1008


@pytest.fixture
async def running_app(start_running_app: StartRunningApp) -> RunningApp:
    return await start_running_app()
