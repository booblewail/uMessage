"""Reply from the inbox: `POST /api/chats/{id}/messages` sends a Message through Beeper Desktop
and stores it as an Outbound Message, shown once even when Beeper reports it back."""

from datetime import timedelta

import pytest
from httpx import AsyncClient

from app.adapters.fakes import FakeMessageSource
from tests.conftest import RunningApp, StartRunningApp
from tests.sources import a_chat, a_message
from tests.ws import inbox_socket


@pytest.fixture
async def running(
    start_running_app: StartRunningApp, message_source: FakeMessageSource
) -> RunningApp:
    message_source.add_chat(
        a_chat("wa-1", title="Climbing crew", active_ago=timedelta(minutes=10)),
        [a_message("m1", sender="Lea", text="Thursday 7pm?", ago=timedelta(minutes=10))],
    )
    message_source.add_chat(
        a_chat("im-1", title="Mum", active_ago=timedelta(minutes=1)),
        [a_message("m2", sender="Mum", text="Lunch Sunday?", ago=timedelta(minutes=1))],
    )
    return await start_running_app()


async def chat_id(client: AsyncClient, title: str) -> int:
    chats = (await client.get("/api/chats")).json()["chats"]
    return next(chat["id"] for chat in chats if chat["title"] == title)


async def thread(client: AsyncClient, chat_id: int) -> list[dict]:
    return (await client.get(f"/api/chats/{chat_id}/messages")).json()["messages"]


async def texts(client: AsyncClient, chat_id: int) -> list[str]:
    return [message["text"] for message in await thread(client, chat_id)]


async def reply(client: AsyncClient, chat_id: int, text: str) -> dict:
    response = await client.post(f"/api/chats/{chat_id}/messages", json={"text": text})
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_reply_is_sent_through_beeper_desktop_and_stored_as_an_outbound_message(
    running: RunningApp, message_source: FakeMessageSource
) -> None:
    crew = await chat_id(running.client, "Climbing crew")

    sent = await reply(running.client, crew, "I'm in!")

    assert message_source.sent == [("wa-1", "I'm in!")]
    assert {key: sent[key] for key in ("chatId", "senderName", "text", "outbound")} == {
        "chatId": crew,
        "senderName": "You",
        "text": "I'm in!",
        "outbound": True,
    }
    assert (await thread(running.client, crew))[-1] == sent


async def test_a_reply_moves_its_chat_to_the_top_and_is_pushed_to_the_inbox(
    running: RunningApp,
) -> None:
    crew = await chat_id(running.client, "Climbing crew")

    async with inbox_socket(running.app) as socket:
        sent = await reply(running.client, crew, "I'm in!")
        event = await socket.receive_until("NEW_MESSAGE")

    chats = (await running.client.get("/api/chats")).json()["chats"]
    assert [chat["title"] for chat in chats] == ["Climbing crew", "Mum"]
    assert (event["message"], event["chat"]) == (sent, chats[0])


async def test_a_reply_loses_the_whitespace_around_it(running: RunningApp) -> None:
    crew = await chat_id(running.client, "Climbing crew")

    sent = await reply(running.client, crew, "  See you there\nBring chalk \n")

    assert sent["text"] == "See you there\nBring chalk"


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
async def test_an_empty_reply_is_rejected_and_not_sent(
    running: RunningApp, message_source: FakeMessageSource, text: str
) -> None:
    crew = await chat_id(running.client, "Climbing crew")

    response = await running.client.post(f"/api/chats/{crew}/messages", json={"text": text})

    assert response.status_code == 422
    assert message_source.sent == []
    assert await texts(running.client, crew) == ["Thursday 7pm?"]


async def test_a_reply_beeper_desktop_fails_to_send_is_reported_and_not_stored(
    running: RunningApp, message_source: FakeMessageSource
) -> None:
    crew = await chat_id(running.client, "Climbing crew")
    message_source.sending_fails = True

    response = await running.client.post(f"/api/chats/{crew}/messages", json={"text": "I'm in!"})

    assert response.status_code == 502
    assert "couldn't send" in response.json()["detail"].lower()
    assert await texts(running.client, crew) == ["Thursday 7pm?"]


async def test_a_reply_while_beeper_desktop_is_not_running_is_reported_and_not_stored(
    running: RunningApp, message_source: FakeMessageSource
) -> None:
    crew = await chat_id(running.client, "Climbing crew")
    message_source.running = False

    response = await running.client.post(f"/api/chats/{crew}/messages", json={"text": "I'm in!"})

    assert response.status_code == 502
    message_source.running = True
    assert await texts(running.client, crew) == ["Thursday 7pm?"]


async def test_a_reply_to_an_unknown_chat_is_not_found(
    running: RunningApp, message_source: FakeMessageSource
) -> None:
    response = await running.client.post("/api/chats/999/messages", json={"text": "Hello?"})

    assert response.status_code == 404
    assert message_source.sent == []


@pytest.mark.parametrize("echo", ["same_id", "final_id"])
async def test_a_reply_reported_back_by_beeper_desktop_is_shown_once(
    running: RunningApp, message_source: FakeMessageSource, echo: str
) -> None:
    # Beeper reports a sent Message back as a new Message, under the id it was sent with or
    # under the final id the network gave it.
    message_source.echo = echo  # type: ignore[assignment]
    crew = await chat_id(running.client, "Climbing crew")

    async with inbox_socket(running.app) as socket:
        sent = await reply(running.client, crew, "I'm in!")
        await socket.receive_until("NEW_MESSAGE")  # the reply itself
        message_source.receive("wa-1", a_message("m3", text="Great", ago=timedelta(0)))
        after_echo = await socket.receive_until("NEW_MESSAGE")  # the echo came before this
        message_source.redeliver_echoes()  # and Beeper reports it again, under its final id
        message_source.receive("wa-1", a_message("m4", text="See you", ago=timedelta(0)))
        await socket.receive_until("NEW_MESSAGE")

    messages = await thread(running.client, crew)
    assert after_echo["message"]["text"] == "Great"
    assert [message["text"] for message in messages] == [
        "Thursday 7pm?",
        "I'm in!",
        "Great",
        "See you",
    ]
    assert messages[1]["id"] == sent["id"]


async def test_the_same_reply_sent_twice_shows_twice(
    running: RunningApp, message_source: FakeMessageSource
) -> None:
    message_source.echo = "final_id"
    crew = await chat_id(running.client, "Climbing crew")

    async with inbox_socket(running.app) as socket:
        await reply(running.client, crew, "ok")
        await reply(running.client, crew, "ok")
        message_source.receive("wa-1", a_message("m3", text="Great", ago=timedelta(0)))
        while (await socket.receive_until("NEW_MESSAGE"))["message"]["text"] != "Great":
            pass

    assert await texts(running.client, crew) == ["Thursday 7pm?", "ok", "ok", "Great"]


async def test_a_message_the_user_sent_from_another_app_shows_as_their_own(
    running: RunningApp, message_source: FakeMessageSource
) -> None:
    async with inbox_socket(running.app) as socket:
        message_source.receive(
            "im-1", a_message("m3", outbound=True, text="Yes, 1pm!", ago=timedelta(0))
        )
        event = await socket.receive_until("NEW_MESSAGE")

    assert {key: event["message"][key] for key in ("senderName", "text", "outbound")} == {
        "senderName": "You",
        "text": "Yes, 1pm!",
        "outbound": True,
    }
    assert event["chat"]["lastMessage"]["outbound"] is True
