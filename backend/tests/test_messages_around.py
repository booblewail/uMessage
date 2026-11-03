"""`GET /api/chats/{id}/messages?around=<messageId>`: a page centred on one Message (an Anchor
Message a link jumps to), which pages on both ways: `before` for older Messages, `after` for
newer ones, back down to the present (`hasNewer` false)."""

from datetime import timedelta

import pytest
from httpx import AsyncClient

from app.adapters.fakes import FakeMessageSource, FakePlanModel
from app.config import Settings
from tests.clock import FakeClock
from tests.conftest import StartApp, StartRunningApp
from tests.plans import days_ahead, detect, new_plan
from tests.sources import a_chat, a_message, messages_minutes_apart
from tests.ws import inbox_socket


async def chat_ids(client: AsyncClient) -> dict[str, int]:
    return {chat["title"]: chat["id"] for chat in (await client.get("/api/chats")).json()["chats"]}


async def message_ids(client: AsyncClient, chat_id: int) -> dict[str, int]:
    page = (await client.get(f"/api/chats/{chat_id}/messages", params={"limit": 200})).json()
    return {message["text"]: message["id"] for message in page["messages"]}


async def get_page(client: AsyncClient, chat_id: int, **params: object) -> dict:
    response = await client.get(f"/api/chats/{chat_id}/messages", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def texts(page: dict) -> list[str]:
    return [message["text"] for message in page["messages"]]


def numbered(*numbers: int) -> list[str]:
    return [f"Message m-{n}" for n in numbers]


@pytest.fixture
async def thirty(start_app: StartApp, message_source: FakeMessageSource) -> tuple[AsyncClient, int]:
    """A Chat whose 30 Messages (m-1 oldest ... m-30 newest) are all stored."""
    message_source.add_chat(a_chat("wa-1", title="Thirty"), messages_minutes_apart("m", 30))
    client = await start_app()
    return client, (await chat_ids(client))["Thirty"]


async def test_a_page_around_a_message_has_it_in_the_middle(
    thirty: tuple[AsyncClient, int],
) -> None:
    client, chat_id = thirty
    ids = await message_ids(client, chat_id)

    page = await get_page(client, chat_id, around=ids["Message m-15"], limit=5)

    assert texts(page) == numbered(13, 14, 15, 16, 17)
    assert (page["hasOlder"], page["olderCursor"]) == (True, ids["Message m-13"])
    assert (page["hasNewer"], page["newerCursor"]) == (True, ids["Message m-17"])


async def test_paging_on_from_around_a_message_gives_the_whole_chat_without_gaps_or_repeats(
    thirty: tuple[AsyncClient, int],
) -> None:
    client, chat_id = thirty
    ids = await message_ids(client, chat_id)
    middle = await get_page(client, chat_id, around=ids["Message m-15"], limit=4)

    older, newer = [middle], [middle]
    while older[-1]["hasOlder"]:
        older.append(await get_page(client, chat_id, before=older[-1]["olderCursor"], limit=4))
        assert len(older) < 20
    while newer[-1]["hasNewer"]:
        newer.append(await get_page(client, chat_id, after=newer[-1]["newerCursor"], limit=4))
        assert len(newer) < 20

    pages = [*reversed(older[1:]), middle, *newer[1:]]
    assert [text for page in pages for text in texts(page)] == numbered(*range(1, 31))
    assert (newer[-1]["hasNewer"], newer[-1]["newerCursor"]) == (False, None)


async def test_a_page_around_a_message_near_either_end_is_still_full(
    thirty: tuple[AsyncClient, int],
) -> None:
    client, chat_id = thirty
    ids = await message_ids(client, chat_id)

    near_newest = await get_page(client, chat_id, around=ids["Message m-29"], limit=5)
    newest = await get_page(client, chat_id, around=ids["Message m-30"], limit=5)
    near_oldest = await get_page(client, chat_id, around=ids["Message m-2"], limit=5)

    assert texts(near_newest) == texts(newest) == numbered(26, 27, 28, 29, 30)
    assert (near_newest["hasNewer"], near_newest["newerCursor"]) == (False, None)
    assert texts(near_oldest) == numbered(1, 2, 3, 4, 5)


async def test_pages_say_whether_there_are_newer_messages(
    thirty: tuple[AsyncClient, int],
) -> None:
    client, chat_id = thirty
    ids = await message_ids(client, chat_id)

    newest = await get_page(client, chat_id, limit=5)
    older = await get_page(client, chat_id, before=newest["olderCursor"], limit=5)
    caught_up = await get_page(client, chat_id, after=ids["Message m-30"], limit=5)

    assert (newest["hasNewer"], newest["newerCursor"]) == (False, None)
    assert texts(older) == numbered(21, 22, 23, 24, 25)
    assert (older["hasNewer"], older["newerCursor"]) == (True, ids["Message m-25"])
    assert caught_up["messages"] == []
    assert (caught_up["hasNewer"], caught_up["newerCursor"]) == (False, None)
    assert (caught_up["hasOlder"], caught_up["olderCursor"]) == (True, ids["Message m-30"])


async def test_an_anchor_message_older_than_the_newest_page_can_be_jumped_to(
    start_running_app: StartRunningApp,
    message_source: FakeMessageSource,
    plan_model: FakePlanModel,
    clock: FakeClock,
    settings: Settings,
) -> None:
    message_source.add_chat(a_chat("ana", title="Ana"), messages_minutes_apart("m", 3))
    running = await start_running_app()
    plan_model.will_decide(new_plan("Dinner", start=days_ahead(3)))
    async with inbox_socket(running.app) as socket:
        dinner = await detect(socket, message_source, clock, settings, "ana", "dinner fri?")
        for n in range(60):  # the Chat moves on: the plan is far back now
            message_source.receive(
                "ana", a_message(f"later-{n}", text=f"later {n}", ago=timedelta(0))
            )
            await socket.receive_until("NEW_MESSAGE")
    client, chat_id = running.client, dinner["chatId"]
    newest = await get_page(client, chat_id, limit=50)
    assert dinner["anchorMessageId"] not in [m["id"] for m in newest["messages"]]

    around = await get_page(client, chat_id, around=dinner["anchorMessageId"], limit=10)

    anchor = next(m for m in around["messages"] if m["id"] == dinner["anchorMessageId"])
    assert anchor["text"] == "dinner fri?"
    assert [e["id"] for e in anchor["detectedEvents"]] == [dinner["id"]]
    assert texts(around)[:4] == [*numbered(1, 2, 3), "dinner fri?"]
    pages = [around]
    while pages[-1]["hasNewer"]:
        pages.append(await get_page(client, chat_id, after=pages[-1]["newerCursor"], limit=10))
        assert len(pages) < 20
    assert texts(pages[-1])[-1] == "later 59"


async def test_a_message_of_another_chat_or_none_at_all_is_not_found(
    start_app: StartApp, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1", title="One"), messages_minutes_apart("one", 3))
    message_source.add_chat(a_chat("wa-2", title="Two"), messages_minutes_apart("two", 3))
    client = await start_app()
    chats = await chat_ids(client)
    other = next(iter((await message_ids(client, chats["Two"])).values()))

    for params in ({"around": other}, {"around": 99999}, {"after": other}, {"after": 99999}):
        response = await client.get(f"/api/chats/{chats['One']}/messages", params=params)
        assert response.status_code == 404, params


async def test_only_one_of_before_after_and_around_can_be_given(
    thirty: tuple[AsyncClient, int],
) -> None:
    client, chat_id = thirty
    ids = list((await message_ids(client, chat_id)).values())

    for params in (
        {"before": ids[5], "after": ids[1]},
        {"around": ids[5], "before": ids[9]},
        {"around": ids[5], "after": ids[1]},
    ):
        response = await client.get(f"/api/chats/{chat_id}/messages", params=params)
        assert response.status_code == 422, params
