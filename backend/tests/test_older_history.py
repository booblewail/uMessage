"""Scroll back past stored history: once a Chat's stored Messages run out, paging back with
`before` carries on with older Messages from Beeper Desktop, until `hasOlder` is false."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from app.adapters.fakes import FakeMessageSource
from app.adapters.protocols import SourceMessage
from tests.conftest import StartApp, StartRunningApp
from tests.sources import a_chat, a_message, messages_minutes_apart
from tests.ws import inbox_socket


async def only_chat_id(client: AsyncClient) -> int:
    [chat] = (await client.get("/api/chats")).json()["chats"]
    return chat["id"]


async def page_back(client: AsyncClient, chat_id: int, *, limit: int) -> list[dict]:
    """Every page from the newest back to the end of history."""
    url = f"/api/chats/{chat_id}/messages"
    pages = [(await client.get(url, params={"limit": limit})).json()]
    while pages[-1]["hasOlder"]:
        before = pages[-1]["olderCursor"]
        response = await client.get(url, params={"limit": limit, "before": before})
        assert response.status_code == 200, response.text
        pages.append(response.json())
        assert len(pages) < 50, "paging back never ended"
    return pages


def history(pages: list[dict]) -> list[str]:
    """The texts of all pages, oldest first."""
    return [message["text"] for page in reversed(pages) for message in page["messages"]]


async def test_paging_back_carries_on_past_the_stored_messages_without_gaps_or_repeats(
    start_app: StartApp, message_source: FakeMessageSource
) -> None:
    # First Import stores the newest 50 of 80 (m-31 to m-80); Beeper holds them all.
    message_source.add_chat(a_chat("wa-1"), messages_minutes_apart("m", 80))
    client = await start_app()

    pages = await page_back(client, await only_chat_id(client), limit=20)

    assert history(pages) == [f"Message m-{n}" for n in range(1, 81)]
    assert [len(page["messages"]) for page in pages] == [20, 20, 20, 20]
    assert (pages[-1]["hasOlder"], pages[-1]["olderCursor"]) == (False, None)


async def test_paging_back_again_gives_the_same_history(
    start_app: StartApp, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1"), messages_minutes_apart("m", 70))
    client = await start_app()
    chat_id = await only_chat_id(client)

    first = history(await page_back(client, chat_id, limit=30))
    second = history(await page_back(client, chat_id, limit=30))

    assert first == second == [f"Message m-{n}" for n in range(1, 71)]


async def test_a_short_chat_says_it_has_no_older_messages(
    start_app: StartApp, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1"), messages_minutes_apart("m", 3))
    client = await start_app()

    pages = await page_back(client, await only_chat_id(client), limit=50)

    assert len(pages) == 1
    assert history(pages) == ["Message m-1", "Message m-2", "Message m-3"]


async def test_beeper_desktop_pages_back_from_where_it_said_a_message_is(
    start_app: StartApp, message_source: FakeMessageSource
) -> None:
    # Beeper pages back by its own position for a Message (its sortKey), not by id; the fake
    # refuses to page back from a Message without the position it reported for it.
    now = datetime.now(UTC)
    messages = [
        SourceMessage(
            source_id=f"m-{n}",
            sender_name="Ana",
            sent_at=now - timedelta(minutes=60 - n),
            text=f"Message m-{n}",
            outbound=False,
            paging_key=f"sort-{n:04d}",
        )
        for n in range(1, 61)
    ]
    message_source.add_chat(a_chat("wa-1"), messages)
    client = await start_app()

    pages = await page_back(client, await only_chat_id(client), limit=25)

    assert history(pages) == [f"Message m-{n}" for n in range(1, 61)]


async def test_a_chat_that_comes_back_to_life_can_be_scrolled_back_to_its_old_messages(
    start_running_app: StartRunningApp, message_source: FakeMessageSource
) -> None:
    # Quiet for months, so First Import left it out; then a new Message arrives.
    old = [a_message(f"old-{n}", ago=timedelta(days=90, minutes=-n)) for n in range(1, 6)]
    message_source.add_chat(a_chat("wa-old", title="Old friend", active_ago=timedelta(days=90)))
    message_source.messages["wa-old"].extend(old)
    running = await start_running_app()
    async with inbox_socket(running.app) as socket:
        message_source.receive("wa-old", a_message("new", text="Long time!", ago=timedelta(0)))
        await socket.receive_until("NEW_MESSAGE")

    pages = await page_back(running.client, await only_chat_id(running.client), limit=3)

    assert history(pages) == [f"Message old-{n}" for n in range(1, 6)] + ["Long time!"]


async def test_older_messages_cannot_be_fetched_while_beeper_desktop_is_not_running(
    start_app: StartApp, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1"), messages_minutes_apart("m", 80))
    client = await start_app()
    chat_id = await only_chat_id(client)
    url = f"/api/chats/{chat_id}/messages"
    message_source.running = False

    stored = (await client.get(url, params={"limit": 200})).json()
    beyond = await client.get(url, params={"limit": 20, "before": stored["olderCursor"]})

    # The stored Messages are still there, and the inbox knows there are older ones.
    assert history([stored]) == [f"Message m-{n}" for n in range(31, 81)]
    assert stored["hasOlder"] is True
    assert beyond.status_code == 503
    message_source.running = True
    later = (await client.get(url, params={"limit": 20, "before": stored["olderCursor"]})).json()
    assert history([later]) == [f"Message m-{n}" for n in range(11, 31)]
