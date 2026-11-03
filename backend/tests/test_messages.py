"""`GET /api/chats/{id}/messages`: a Chat's Messages, a page at a time.

A page holds the newest `limit` Messages older than `before` (all Messages without it), in
chronological order (oldest first); `olderCursor` is the `before` for the next page back.
"""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from app.adapters.fakes import FakeMessageSource
from tests.conftest import StartApp
from tests.sources import a_chat, a_message, messages_minutes_apart


async def only_chat_id(client: AsyncClient) -> int:
    [chat] = (await client.get("/api/chats")).json()["chats"]
    return chat["id"]


def texts(page: dict) -> list[str]:
    return [message["text"] for message in page["messages"]]


async def test_messages_show_sender_time_text_and_whether_they_are_outbound(
    start_app: StartApp, message_source: FakeMessageSource
) -> None:
    theirs = a_message("m1", sender="Priya", text="Dinner Friday?", ago=timedelta(minutes=10))
    mine = a_message("m2", outbound=True, text="Yes! 8pm?", ago=timedelta(minutes=5))
    message_source.add_chat(a_chat("wa-1"), [theirs, mine])
    client = await start_app()
    chat_id = await only_chat_id(client)

    response = await client.get(f"/api/chats/{chat_id}/messages")

    assert response.status_code == 200
    page = response.json()
    assert [
        {key: value for key, value in message.items() if key != "id"}
        for message in page["messages"]
    ] == [
        {
            "chatId": chat_id,
            "senderName": "Priya",
            "sentAt": page["messages"][0]["sentAt"],
            "text": "Dinner Friday?",
            "outbound": False,
            "detectedEvents": [],
        },
        {
            "chatId": chat_id,
            "senderName": "You",
            "sentAt": page["messages"][1]["sentAt"],
            "text": "Yes! 8pm?",
            "outbound": True,
            "detectedEvents": [],
        },
    ]
    assert [datetime.fromisoformat(m["sentAt"]) for m in page["messages"]] == [
        theirs.sent_at,
        mine.sent_at,
    ]
    assert (page["hasOlder"], page["olderCursor"]) == (False, None)


async def test_a_page_holds_the_newest_messages_oldest_first(
    start_app: StartApp, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1"), messages_minutes_apart("m", 12))
    client = await start_app()
    chat_id = await only_chat_id(client)

    page = (await client.get(f"/api/chats/{chat_id}/messages", params={"limit": 5})).json()

    assert texts(page) == [f"Message m-{n}" for n in range(8, 13)]
    assert page["hasOlder"] is True
    assert page["olderCursor"] == page["messages"][0]["id"]


async def test_older_messages_are_paged_back_with_before(
    start_app: StartApp, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("wa-1"), messages_minutes_apart("m", 12))
    client = await start_app()
    chat_id = await only_chat_id(client)
    url = f"/api/chats/{chat_id}/messages"

    pages = [(await client.get(url, params={"limit": 5})).json()]
    while pages[-1]["hasOlder"]:
        before = pages[-1]["olderCursor"]
        pages.append((await client.get(url, params={"limit": 5, "before": before})).json())

    assert [texts(page) for page in pages] == [
        [f"Message m-{n}" for n in range(8, 13)],
        [f"Message m-{n}" for n in range(3, 8)],
        ["Message m-1", "Message m-2"],
    ]
    assert pages[-1]["olderCursor"] is None


async def test_messages_sent_at_the_same_moment_page_without_gaps_or_repeats(
    start_app: StartApp, message_source: FakeMessageSource
) -> None:
    same_time = datetime.now(UTC) - timedelta(minutes=3)
    message_source.add_chat(
        a_chat("wa-1"), [a_message(f"m{n}", at=same_time, text=f"Burst {n}") for n in range(1, 6)]
    )
    client = await start_app()
    chat_id = await only_chat_id(client)
    url = f"/api/chats/{chat_id}/messages"

    first = (await client.get(url, params={"limit": 3})).json()
    second = (await client.get(url, params={"limit": 3, "before": first["olderCursor"]})).json()

    assert sorted(texts(first) + texts(second)) == [f"Burst {n}" for n in range(1, 6)]


async def test_messages_of_an_unknown_chat_are_not_found(start_app: StartApp) -> None:
    client = await start_app()

    response = await client.get("/api/chats/999/messages")

    assert response.status_code == 404


async def test_a_before_cursor_from_another_chat_is_not_found(
    start_app: StartApp, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(a_chat("a", active_ago=timedelta(minutes=1)), [a_message("a1")])
    message_source.add_chat(a_chat("b", active_ago=timedelta(minutes=2)), [a_message("b1")])
    client = await start_app()
    chat_a, chat_b = [chat["id"] for chat in (await client.get("/api/chats")).json()["chats"]]
    message_in_b = (await client.get(f"/api/chats/{chat_b}/messages")).json()["messages"][0]

    response = await client.get(
        f"/api/chats/{chat_a}/messages", params={"before": message_in_b["id"]}
    )

    assert response.status_code == 404
