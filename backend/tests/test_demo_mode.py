"""Demo mode (`UMESSAGE_MODE=demo`) runs the real app with fake adapters and no credentials."""

import pytest
from asgi_lifespan import LifespanManager

from app.adapters.demo_fixtures import demo_message_source
from app.adapters.protocols import ChatKind, Platform
from app.main import build_app
from tests.conftest import http_client, make_settings, wait_for_first_import
from tests.ws import inbox_socket


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

    assert (body["mode"], body["messageSource"]) == (
        "demo",
        {"name": "Beeper Desktop", "running": beeper_running},
    )


async def test_demo_mode_shows_fixture_chats_on_all_five_platforms(database_url: str) -> None:
    settings = make_settings(database_url, umessage_mode="demo")

    async with LifespanManager(build_app(settings)) as manager, http_client(manager.app) as client:
        await wait_for_first_import(client)
        chats = (await client.get("/api/chats")).json()["chats"]
        threads = [
            (await client.get(f"/api/chats/{chat['id']}/messages")).json()["messages"]
            for chat in chats
        ]

    assert {chat["platform"] for chat in chats} == {platform.value for platform in Platform}
    assert all(thread for thread in threads)
    assert any(message["outbound"] for thread in threads for message in thread)


async def test_demo_mode_leaves_out_its_fixture_discord_server_channel(database_url: str) -> None:
    server_channels = [
        chat.title for chat in demo_message_source().chats if chat.kind is ChatKind.SERVER_CHANNEL
    ]
    settings = make_settings(database_url, umessage_mode="demo")

    async with LifespanManager(build_app(settings)) as manager, http_client(manager.app) as client:
        await wait_for_first_import(client)
        titles = {chat["title"] for chat in (await client.get("/api/chats")).json()["chats"]}

    assert server_channels
    assert not titles & set(server_channels)


async def test_demo_mode_trickles_in_new_messages_that_arrive_live(database_url: str) -> None:
    settings = make_settings(database_url, umessage_mode="demo", demo_new_message_seconds=0.01)

    async with LifespanManager(build_app(settings)) as manager, http_client(manager.app) as client:
        await wait_for_first_import(client)
        async with inbox_socket(manager.app) as socket:
            events = [await socket.receive_until("NEW_MESSAGE") for _ in range(3)]
        titles = {chat["title"] for chat in (await client.get("/api/chats")).json()["chats"]}

    assert len({event["message"]["id"] for event in events}) == 3
    assert "Dana Ortiz" in titles  # one of the first scripted Messages starts a new Chat


async def test_demo_mode_keeps_trickling_in_new_messages_after_a_restart(
    database_url: str,
) -> None:
    # The demo Message Source starts afresh on every start (e.g. `make dev` reloading), while
    # the database, with its cursor and the Messages already trickled in, is kept.
    settings = make_settings(database_url, umessage_mode="demo", demo_new_message_seconds=0.01)
    async with LifespanManager(build_app(settings)) as manager, http_client(manager.app) as client:
        await wait_for_first_import(client)
        async with inbox_socket(manager.app) as socket:
            before = [await socket.receive_until("NEW_MESSAGE") for _ in range(3)]

    async with LifespanManager(build_app(settings)) as manager:
        async with inbox_socket(manager.app) as socket:
            after = [await socket.receive_until("NEW_MESSAGE") for _ in range(3)]

    assert len({event["message"]["id"] for event in after}) == 3
    assert not {event["message"]["id"] for event in after} & {
        event["message"]["id"] for event in before
    }
