"""First Import: the one-time load of existing Chats and recent Messages from Beeper Desktop."""

from datetime import timedelta

from asgi_lifespan import LifespanManager
from httpx import AsyncClient

from app.adapters.fakes import FakeMessageSource
from app.adapters.protocols import ChatKind, Platform
from app.config import Settings
from tests.conftest import http_client, make_app, wait_for_first_import
from tests.sources import a_chat, a_message, messages_minutes_apart


async def chat_titles(client: AsyncClient) -> list[str]:
    return [chat["title"] for chat in (await client.get("/api/chats")).json()["chats"]]


async def all_message_texts(client: AsyncClient, chat_id: int) -> list[str]:
    page = (await client.get(f"/api/chats/{chat_id}/messages", params={"limit": 200})).json()
    return [message["text"] for message in page["messages"]]


async def test_first_import_brings_in_the_chats_and_messages_of_the_message_source(
    settings: Settings, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1", title="Climbing crew"), [a_message("m1", text="Hi")])
    message_source.add_chat(
        a_chat("ig-1", platform=Platform.INSTAGRAM, title="Priya"), [a_message("m2", text="Yo")]
    )

    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            first_import = await wait_for_first_import(client)
            chats = (await client.get("/api/chats")).json()["chats"]

    assert first_import == {
        "state": "completed",
        "chatsTotal": 2,
        "chatsImported": 2,
        "error": None,
    }
    assert {chat["title"]: chat["lastMessage"]["text"] for chat in chats} == {
        "Climbing crew": "Hi",
        "Priya": "Yo",
    }


async def test_first_import_reports_progress_while_it_runs(
    settings: Settings, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1"), [a_message("m1")])
    message_source.add_chat(a_chat("wa-2"), [a_message("m2")])
    message_source.messages_readable.clear()

    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            # Startup finished although First Import can't read any Messages yet.
            during = await wait_for_first_import(client, until="running")
            message_source.messages_readable.set()
            after = await wait_for_first_import(client)

    assert during == {"state": "running", "chatsTotal": 2, "chatsImported": 0, "error": None}
    assert after["chatsImported"] == 2


async def test_first_import_keeps_the_last_50_messages_of_each_chat(
    settings: Settings, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1"), messages_minutes_apart("m", 60))

    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            await wait_for_first_import(client)
            chat_id = (await client.get("/api/chats")).json()["chats"][0]["id"]
            # Older Messages come from Beeper Desktop on demand; without it, only the stored
            # ones are there.
            message_source.running = False
            texts = await all_message_texts(client, chat_id)

    assert texts == [f"Message m-{n}" for n in range(11, 61)]


async def test_first_import_leaves_out_chats_quiet_for_more_than_30_days(
    settings: Settings, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("recent", title="Recent", active_ago=timedelta(days=29)))
    message_source.add_chat(a_chat("stale", title="Stale", active_ago=timedelta(days=31)))

    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            await wait_for_first_import(client)
            titles = await chat_titles(client)

    assert titles == ["Recent"]


async def test_first_import_leaves_out_discord_server_channels(
    settings: Settings, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(
        a_chat("dc-dm", platform=Platform.DISCORD, title="jules"), [a_message("m1")]
    )
    message_source.add_chat(
        a_chat("dc-gdm", platform=Platform.DISCORD, kind=ChatKind.GROUP, title="Raid night"),
        [a_message("m2")],
    )
    message_source.add_chat(
        a_chat("dc-srv", platform=Platform.DISCORD, kind=ChatKind.SERVER_CHANNEL, title="#general"),
        [a_message("m3")],
    )

    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            first_import = await wait_for_first_import(client)
            titles = await chat_titles(client)

    assert sorted(titles) == ["Raid night", "jules"]
    assert first_import["chatsTotal"] == 2


async def test_first_import_waits_until_beeper_desktop_is_running(
    settings: Settings, message_source: FakeMessageSource
) -> None:
    message_source.running = False
    message_source.add_chat(a_chat("wa-1", title="Climbing crew"), [a_message("m1")])

    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            waiting = await wait_for_first_import(client, until="waiting")
            titles_while_waiting = await chat_titles(client)
            message_source.running = True
            await wait_for_first_import(client)
            titles_after = await chat_titles(client)

    assert waiting == {"state": "waiting", "chatsTotal": None, "chatsImported": 0, "error": None}
    assert (titles_while_waiting, titles_after) == ([], ["Climbing crew"])


async def test_first_import_carries_on_when_beeper_desktop_comes_back_mid_import(
    settings: Settings, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1", title="One"), [a_message("m1")])
    message_source.add_chat(a_chat("wa-2", title="Two"), [a_message("m2")])
    message_source.messages_readable.clear()

    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            await wait_for_first_import(client, until="running")
            message_source.running = False  # Beeper Desktop quits mid-import
            message_source.messages_readable.set()
            await wait_for_first_import(client, until="waiting")
            message_source.running = True
            completed = await wait_for_first_import(client)
            titles = await chat_titles(client)

    assert completed["chatsImported"] == 2
    assert sorted(titles) == ["One", "Two"]


async def test_first_import_does_not_run_again_after_a_restart(
    settings: Settings, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1", title="Before"), [a_message("m1")])
    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            await wait_for_first_import(client)

    message_source.add_chat(a_chat("wa-2", title="After"), [a_message("m2")])
    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            first_import = (await client.get("/api/status")).json()["firstImport"]
            titles = await chat_titles(client)

    assert first_import["state"] == "completed"
    assert titles == ["Before"]


async def test_failed_first_import_is_reported_and_runs_again_on_the_next_start(
    settings: Settings, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1", title="Readable"), [a_message("m1")])
    message_source.add_chat(a_chat("wa-2", title="Broken"), [a_message("m2")])
    message_source.failing_chats = {"wa-2"}
    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            failed = await wait_for_first_import(client, until="failed")

    message_source.failing_chats = set()
    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            completed = await wait_for_first_import(client)
            titles = await chat_titles(client)

    assert failed["error"] == "can't read the Messages of wa-2"
    assert completed["chatsImported"] == 2
    assert sorted(titles) == ["Broken", "Readable"]


async def test_importing_the_same_messages_again_creates_no_duplicates(
    settings: Settings, message_source: FakeMessageSource
) -> None:
    # The first attempt stores Chat wa-1 and then fails on wa-2; the retry imports wa-1 again.
    message_source.add_chat(a_chat("wa-1", active_ago=timedelta(minutes=1)), [a_message("m1")])
    message_source.add_chat(a_chat("wa-2", active_ago=timedelta(minutes=2)), [a_message("m2")])
    message_source.failing_chats = {"wa-2"}
    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            await wait_for_first_import(client, until="failed")

    message_source.failing_chats = set()
    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            await wait_for_first_import(client)
            chats = (await client.get("/api/chats")).json()["chats"]
            texts = {chat["title"]: await all_message_texts(client, chat["id"]) for chat in chats}

    assert texts == {"Chat wa-1": ["Message m1"], "Chat wa-2": ["Message m2"]}


async def test_a_message_reported_twice_is_stored_once(
    settings: Settings, message_source: FakeMessageSource
) -> None:
    message = a_message("m1", text="Dinner at 8?")
    message_source.add_chat(a_chat("wa-1"), [message, message])

    async with LifespanManager(make_app(settings, message_source)) as manager:
        async with http_client(manager.app) as client:
            await wait_for_first_import(client)
            chat_id = (await client.get("/api/chats")).json()["chats"][0]["id"]
            texts = await all_message_texts(client, chat_id)

    assert texts == ["Dinner at 8?"]
