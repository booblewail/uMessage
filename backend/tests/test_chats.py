"""`GET /api/chats`: every Chat in the inbox, newest first, optionally for one Platform."""

from datetime import datetime, timedelta

import pytest

from app.adapters.fakes import FakeMessageSource
from app.adapters.protocols import ChatKind, Platform
from tests.conftest import StartApp
from tests.sources import a_chat, a_message


async def test_a_chat_shows_its_platform_kind_title_and_last_message(
    start_app: StartApp, message_source: FakeMessageSource
) -> None:
    last = a_message("m2", sender="Priya", text="See you at 7!", ago=timedelta(minutes=2))
    message_source.add_chat(
        a_chat("ig-1", platform=Platform.INSTAGRAM, kind=ChatKind.GROUP, title="Book club"),
        [a_message("m1", outbound=True, text="Running late", ago=timedelta(minutes=9)), last],
    )
    client = await start_app()

    response = await client.get("/api/chats")

    assert response.status_code == 200
    [chat] = response.json()["chats"]
    assert isinstance(chat["id"], int)
    assert {key: value for key, value in chat.items() if key not in ("id", "lastMessage")} == {
        "platform": "instagram",
        "kind": "group",
        "title": "Book club",
        "lastMessageAt": chat["lastMessage"]["sentAt"],
        "excluded": False,
    }
    assert datetime.fromisoformat(chat["lastMessageAt"]) == last.sent_at
    assert chat["lastMessage"] == {
        "senderName": "Priya",
        "text": "See you at 7!",
        "sentAt": chat["lastMessageAt"],
        "outbound": False,
    }


async def test_chats_are_listed_newest_first_by_their_last_message(
    start_app: StartApp, message_source: FakeMessageSource
) -> None:
    # Beeper counts reactions and the like as activity; the inbox goes by Messages.
    message_source.add_chat(
        a_chat("a", title="Busy but quiet", active_ago=timedelta(seconds=10)),
        [a_message("a1", ago=timedelta(hours=3))],
    )
    message_source.add_chat(
        a_chat("b", title="Latest", active_ago=timedelta(minutes=1)),
        [a_message("b1", ago=timedelta(minutes=1))],
    )
    message_source.add_chat(
        a_chat("c", title="Earlier", active_ago=timedelta(hours=1)),
        [a_message("c1", ago=timedelta(hours=1))],
    )
    client = await start_app()

    chats = (await client.get("/api/chats")).json()["chats"]

    assert [chat["title"] for chat in chats] == ["Latest", "Earlier", "Busy but quiet"]


async def test_a_chat_without_text_messages_sorts_by_its_last_activity(
    start_app: StartApp, message_source: FakeMessageSource
) -> None:
    message_source.add_chat(
        a_chat("a", title="Older", active_ago=timedelta(hours=2)),
        [a_message("a1", ago=timedelta(hours=2))],
    )
    photos_only = a_chat("b", title="Photos only", active_ago=timedelta(hours=1))
    message_source.add_chat(photos_only)
    client = await start_app()

    chats = (await client.get("/api/chats")).json()["chats"]

    assert [(chat["title"], chat["lastMessage"]) for chat in chats] == [
        ("Photos only", None),
        ("Older", chats[1]["lastMessage"]),
    ]
    assert datetime.fromisoformat(chats[0]["lastMessageAt"]) == photos_only.last_activity


@pytest.mark.parametrize("platform", list(Platform))
async def test_chats_can_be_narrowed_to_one_platform(
    start_app: StartApp, message_source: FakeMessageSource, platform: Platform
) -> None:
    for each in Platform:
        message_source.add_chat(
            a_chat(f"{each}-chat", platform=each, title=f"{each} chat"), [a_message(f"{each}-m")]
        )
    client = await start_app()

    chats = (await client.get("/api/chats", params={"platform": platform.value})).json()["chats"]

    assert [(chat["title"], chat["platform"]) for chat in chats] == [
        (f"{platform} chat", platform.value)
    ]


async def test_an_unknown_platform_filter_is_rejected(start_app: StartApp) -> None:
    client = await start_app()

    response = await client.get("/api/chats", params={"platform": "telegram"})

    assert response.status_code == 422


async def test_the_inbox_is_empty_before_anything_is_imported(start_app: StartApp) -> None:
    client = await start_app()

    response = await client.get("/api/chats")

    assert response.json() == {"chats": []}


@pytest.mark.parametrize("path", ["/api/chats", "/api/chats/1/messages"])
async def test_chats_and_messages_need_the_api_token(start_app: StartApp, path: str) -> None:
    client = await start_app()

    response = await client.get(path, headers={"Authorization": ""})

    assert response.status_code == 401
