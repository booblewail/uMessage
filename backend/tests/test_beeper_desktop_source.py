"""Contract tests for the real Beeper Desktop Message Source (#13).

They drive `BeeperDesktopMessageSource` against `FakeBeeperDesktop`: Beeper Desktop's local API
as its official SDK (github.com/beeper/desktop-api-js) documents it, served through
`httpx.MockTransport` from the SYNTHETIC, hand-written fixtures in
`tests/fixtures/beeper_sdk_shape/` (none of them is recorded).

README: once the Phase 0 spike (#2) has run on a real Mac, replace the synthetic fixtures with
the recorded ones (`backend/scripts/beeper_spike.py` writes them to
`backend/tests/fixtures/beeper/`), and adjust the mappings in `app/adapters/beeper_desktop.py`
(each one Phase 0 must confirm says so in its docstring) until these tests pass on them.
"""

import itertools
import json
import logging
import socket
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager

from app.adapters.beeper_desktop import BeeperDesktopApiError, BeeperDesktopMessageSource
from app.adapters.fakes import FakeCalendar, FakePlanModel
from app.adapters.protocols import (
    ChatKind,
    MessageSourceUnavailableError,
    Platform,
    SourceMessage,
    SourceMessageRef,
)
from app.main import create_app
from tests.conftest import (
    RETRY_SECONDS,
    eventually,
    http_client,
    make_settings,
    wait_for_first_import,
)

FIXTURES = Path(__file__).parent / "fixtures" / "beeper_sdk_shape"
BASE_URL = "http://127.0.0.1:23373"
BEEPER_TOKEN = "test-beeper-access-token"
SELF_ID = "@sam:beeper.com"
T0 = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
FAMILY = "!wa-family:beeper.local"
ALEX = "!imsg-alex:beeper.local"
TELEGRAM = "!tg-news:beeper.local"

Json = dict[str, Any]


def load_items(name: str) -> list[Json]:
    return json.loads((FIXTURES / f"{name}.json").read_text())["items"]


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def shifted(value: str, by: timedelta) -> str:
    return iso(parse(value) + by)


class FakeBeeperDesktop:
    """Beeper Desktop's local API with the fixture Chats and Messages, as the SDK documents it.

    Pages hold at most `page_size` items (newest first) so paging is exercised; a page's
    `oldestCursor` with `direction=before` gives the next one. Chat Message pages also take a
    Message's `sortKey` as the cursor (the adapter's assumption, which Phase 0 must confirm).
    Every request is recorded in `requests`; set `answer` to answer every request with it.
    """

    def __init__(self, *, page_size: int = 3, shift: timedelta = timedelta(0)) -> None:
        self.page_size = page_size
        self.accounts = load_items("accounts")
        self.accounts_wrapped = False
        self.chat_search_available = True
        self.chats: dict[str, Json] = {}
        for chat in load_items("chats"):
            chat["lastActivity"] = shifted(chat["lastActivity"], shift)
            self.chats[chat["id"]] = chat
        self.messages = load_items("messages")
        for message in self.messages:
            message["timestamp"] = shifted(message["timestamp"], shift)
        self._sort_keys = itertools.count(5000)
        self._sent_numbers = itertools.count(1)
        self.requests: list[httpx.Request] = []
        self.answer: Callable[[httpx.Request], httpx.Response] | None = None

    def source(self, **kwargs: Any) -> BeeperDesktopMessageSource:
        kwargs.setdefault("access_token", BEEPER_TOKEN)
        return BeeperDesktopMessageSource(
            BASE_URL, transport=httpx.MockTransport(self.handle), **kwargs
        )

    def add_message(
        self,
        chat_id: str,
        message_id: str,
        at: datetime,
        *,
        text: str | None = "Hello",
        type_: str = "TEXT",
        is_sender: bool = False,
    ) -> None:
        self.messages.append(
            {
                "id": message_id,
                "chatID": chat_id,
                "accountID": self.chats[chat_id]["accountID"],
                "senderID": SELF_ID if is_sender else f"{chat_id}-someone",
                "senderName": "Sam Taylor" if is_sender else "Someone",
                "sortKey": str(next(self._sort_keys)),
                "timestamp": iso(at),
                "type": type_,
                "isSender": is_sender,
                **({"text": text} if text is not None else {}),
            }
        )

    def requested(self, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == path]

    # --- the API ------------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.answer is not None:
            return self.answer(request)
        if request.headers.get("Authorization") != f"Bearer {BEEPER_TOKEN}":
            return httpx.Response(401, json={"error": "invalid access token"})
        path, params = request.url.path, request.url.params
        parts = path.strip("/").split("/")
        if request.method == "POST" and parts[:2] == ["v1", "chats"] and parts[3:] == ["messages"]:
            return self._send(parts[2], json.loads(request.content))
        if request.method != "GET":
            return httpx.Response(405)
        if path == "/v1/info":
            return httpx.Response(200, json=load_raw("info"))
        if path == "/v1/accounts":
            body = {"items": self.accounts} if self.accounts_wrapped else self.accounts
            return httpx.Response(200, json=body)
        if path == "/v1/chats/search":
            if not self.chat_search_available:
                return httpx.Response(404, json={"error": "not found"})
            after = parse(params["lastActivityAfter"])
            chats = [c for c in self.chats.values() if parse(c["lastActivity"]) > after]
            return self._offset_page(sorted(chats, key=_by_activity, reverse=True), params)
        if path == "/v1/chats":
            chats = sorted(self.chats.values(), key=_by_activity, reverse=True)
            return self._offset_page(chats, params)
        if path == "/v1/messages/search":
            after = parse(params["dateAfter"])
            found = [m for m in self.messages if parse(m["timestamp"]) > after]
            found.sort(key=lambda m: (parse(m["timestamp"]), int(m["sortKey"])), reverse=True)
            return self._offset_page(found, params)
        if parts[:2] == ["v1", "chats"] and len(parts) == 3:
            chat = self.chats.get(parts[2])
            return httpx.Response(200, json=chat) if chat else httpx.Response(404)
        if parts[:2] == ["v1", "chats"] and parts[3:] == ["messages"]:
            return self._chat_messages(parts[2], params)
        return httpx.Response(404, json={"error": f"no route {path}"})

    def _offset_page(self, items: list[Json], params: httpx.QueryParams) -> httpx.Response:
        start = int(params["cursor"].removeprefix("offset:")) if "cursor" in params else 0
        if "cursor" in params:
            assert params.get("direction") == "before"
        size = min(int(params.get("limit", self.page_size)), self.page_size)
        page = items[start : start + size]
        end = start + len(page)
        return httpx.Response(
            200,
            json={
                "items": page,
                "hasMore": end < len(items),
                "oldestCursor": f"offset:{end}",
                "newestCursor": f"offset:{start}",
            },
        )

    def _chat_messages(self, chat_id: str, params: httpx.QueryParams) -> httpx.Response:
        if chat_id not in self.chats:
            return httpx.Response(404)
        assert "limit" not in params  # the endpoint has no limit parameter
        messages = sorted(
            (m for m in self.messages if m["chatID"] == chat_id),
            key=lambda m: int(m["sortKey"]),
            reverse=True,
        )
        if "cursor" in params:
            assert params.get("direction") == "before"
            before = int(params["cursor"].removeprefix("sortkey:"))
            messages = [m for m in messages if int(m["sortKey"]) < before]
        page = messages[: self.page_size]
        return httpx.Response(
            200,
            json={
                "items": page,
                "hasMore": len(messages) > len(page),
                "oldestCursor": f"sortkey:{page[-1]['sortKey']}" if page else None,
                "newestCursor": f"sortkey:{page[0]['sortKey']}" if page else None,
            },
        )

    def _send(self, chat_id: str, body: Json) -> httpx.Response:
        if chat_id not in self.chats:
            return httpx.Response(404)
        number = next(self._sent_numbers)
        # Like Beeper, the sent Message shows up later under a final id.
        self.add_message(
            chat_id, f"sent-{number}", datetime.now(UTC), text=body["text"], is_sender=True
        )
        return httpx.Response(
            200, json={"chatID": chat_id, "pendingMessageID": f"pending-{number}"}
        )


def load_raw(name: str) -> Json:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _by_activity(chat: Json) -> datetime:
    return parse(chat["lastActivity"])


def fixed_clock(moment: datetime = T0) -> Callable[[], datetime]:
    return lambda: moment


def unused_local_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def beeper() -> FakeBeeperDesktop:
    return FakeBeeperDesktop()


# --- status ---------------------------------------------------------------------------


async def reported_status(database_url: str, source: BeeperDesktopMessageSource) -> object:
    app = create_app(
        make_settings(database_url, umessage_mode="real"),
        message_source=source,
        plan_model=FakePlanModel(),
        calendar=FakeCalendar(),
    )
    async with LifespanManager(app) as manager, http_client(manager.app) as client:
        return (await client.get("/api/status")).json()["messageSource"]


async def test_beeper_desktop_answering_with_the_access_token_counts_as_running(
    database_url: str, beeper: FakeBeeperDesktop
) -> None:
    body = await reported_status(database_url, beeper.source())

    assert body == {"name": "Beeper Desktop", "running": True}
    info = beeper.requested("/v1/info")[0]
    assert info.headers["Authorization"] == f"Bearer {BEEPER_TOKEN}"


async def test_beeper_desktop_rejecting_the_access_token_counts_as_not_running_and_says_why(
    database_url: str, beeper: FakeBeeperDesktop, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.adapters.beeper_desktop"):
        body = await reported_status(database_url, beeper.source(access_token="wrong"))

    assert body == {"name": "Beeper Desktop", "running": False}
    assert "BEEPER_ACCESS_TOKEN" in caplog.text


async def test_any_other_answer_from_beeper_desktop_counts_as_running(database_url: str) -> None:
    # e.g. a Beeper Desktop version without /v1/info: something is listening there.
    source = BeeperDesktopMessageSource(
        BASE_URL, transport=httpx.MockTransport(lambda _: httpx.Response(404))
    )

    assert await reported_status(database_url, source) == {
        "name": "Beeper Desktop",
        "running": True,
    }


async def test_beeper_desktop_timing_out_counts_as_not_running(database_url: str) -> None:
    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    source = BeeperDesktopMessageSource(BASE_URL, transport=httpx.MockTransport(hang))

    assert await reported_status(database_url, source) == {
        "name": "Beeper Desktop",
        "running": False,
    }


async def test_nothing_listening_where_beeper_desktop_should_be_counts_as_not_running(
    database_url: str,
) -> None:
    source = BeeperDesktopMessageSource(f"http://127.0.0.1:{unused_local_port()}")

    assert await reported_status(database_url, source) == {
        "name": "Beeper Desktop",
        "running": False,
    }


# --- Chats ----------------------------------------------------------------------------

EXPECTED_CHATS = {
    ALEX: (Platform.IMESSAGE, ChatKind.ONE_TO_ONE, "Alex Chen"),
    "!ig-climbing:beeper.local": (Platform.INSTAGRAM, ChatKind.GROUP, "Climbing crew"),
    "!fb-jordan:beeper.local": (Platform.MESSENGER, ChatKind.ONE_TO_ONE, "Jordan Lee"),
    # No `network` on the Chat: its account's network ("Facebook Messenger") decides.
    "!fb-priya:beeper.local": (Platform.MESSENGER, ChatKind.ONE_TO_ONE, "Priya Shah"),
    FAMILY: (Platform.WHATSAPP, ChatKind.GROUP, "Family"),
    "!dc-riley:beeper.local": (Platform.DISCORD, ChatKind.ONE_TO_ONE, "Riley"),
    "!dc-weekend:beeper.local": (Platform.DISCORD, ChatKind.GROUP, "Weekend plans"),
    # More members than a Discord group DM can have.
    "!dc-general:beeper.local": (Platform.DISCORD, ChatKind.SERVER_CHANNEL, "general"),
    # Titled like a guild channel.
    "!dc-announcements:beeper.local": (
        Platform.DISCORD,
        ChatKind.SERVER_CHANNEL,
        "#announcements",
    ),
    # The members of a merged Chat are listed; the merged parent holds no Messages.
    "!wa-casey:beeper.local": (Platform.WHATSAPP, ChatKind.ONE_TO_ONE, "Casey"),
    "!ig-casey:beeper.local": (Platform.INSTAGRAM, ChatKind.ONE_TO_ONE, "Casey"),
}
ACTIVE_SINCE = datetime(2026, 10, 1, tzinfo=UTC)


def listed(chats: Any) -> dict[str, tuple[Platform, ChatKind, str]]:
    return {chat.source_id: (chat.platform, chat.kind, chat.title) for chat in chats}


async def test_lists_chats_on_the_five_platforms_with_their_kind(beeper: FakeBeeperDesktop) -> None:
    chats = await beeper.source().list_chats(active_since=ACTIVE_SINCE)

    # Telegram is not a Platform, the merged parent and the old Chat are left out.
    assert listed(chats) == EXPECTED_CHATS
    family = next(chat for chat in chats if chat.source_id == FAMILY)
    assert family.last_activity == datetime(2026, 10, 20, 16, 5, tzinfo=UTC)
    searches = beeper.requested("/v1/chats/search")
    assert len(searches) > 1  # paged
    assert parse(searches[0].url.params["lastActivityAfter"]) <= ACTIVE_SINCE
    assert searches[1].url.params["direction"] == "before"


async def test_accounts_may_come_wrapped_in_items(beeper: FakeBeeperDesktop) -> None:
    beeper.accounts_wrapped = True

    chats = await beeper.source().list_chats(active_since=ACTIVE_SINCE)

    assert listed(chats) == EXPECTED_CHATS


async def test_lists_chats_without_chat_search(beeper: FakeBeeperDesktop) -> None:
    beeper.chat_search_available = False

    chats = await beeper.source().list_chats(active_since=ACTIVE_SINCE)

    assert listed(chats) == EXPECTED_CHATS  # the Chat last active in August is left out
    assert beeper.requested("/v1/chats")


@pytest.mark.parametrize(
    ("network", "platform"),
    [
        ("iMessage", Platform.IMESSAGE),
        ("IMESSAGE", Platform.IMESSAGE),
        ("Instagram", Platform.INSTAGRAM),
        ("instagram", Platform.INSTAGRAM),
        ("Messenger", Platform.MESSENGER),
        ("Facebook Messenger", Platform.MESSENGER),
        ("Facebook", Platform.MESSENGER),
        ("WhatsApp", Platform.WHATSAPP),
        ("whatsapp", Platform.WHATSAPP),
        ("Discord", Platform.DISCORD),
        ("Telegram", None),
        ("Signal", None),
        ("Google Messages", None),
    ],
)
async def test_platform_comes_from_the_network_name_in_any_case(
    beeper: FakeBeeperDesktop, network: str, platform: Platform | None
) -> None:
    beeper.chats[ALEX]["network"] = network

    chats = await beeper.source().list_chats(active_since=ACTIVE_SINCE)

    alex = [chat.platform for chat in chats if chat.source_id == ALEX]
    assert alex == ([platform] if platform else [])


# --- Messages -------------------------------------------------------------------------


def summary(messages: Any) -> list[tuple[str, str, str, bool]]:
    return [(m.source_id, m.sender_name, m.text, m.outbound) for m in messages]


async def test_recent_messages_are_the_newest_text_messages_mapped(
    beeper: FakeBeeperDesktop,
) -> None:
    messages = await beeper.source().recent_messages(FAMILY, limit=4)

    # The reaction and the photo without a caption are not Messages; oldest first.
    assert summary(messages) == [
        ("wa-f-2", "Mum", "Look at this cake", False),
        ("wa-f-4", "Dad", "I'll bring dessert", False),  # name from the Chat's participants
        ("wa-f-5", "You", "Sounds good", True),
        ("wa-f-7", "Mum", "Dinner at ours on Sunday at 6?", False),
    ]
    newest = messages[-1]
    assert newest == SourceMessage(
        source_id="wa-f-7",
        sender_name="Mum",
        sent_at=datetime(2026, 10, 20, 16, 5, tzinfo=UTC),
        text="Dinner at ours on Sunday at 6?",
        outbound=False,
        paging_key="1007",
    )
    pages = beeper.requested(f"/v1/chats/{FAMILY}/messages")
    assert [dict(p.url.params) for p in pages] == [
        {},
        {"cursor": "sortkey:1005", "direction": "before"},
    ]
    assert b"%3A" in pages[0].url.raw_path  # the Chat id is encoded into the path


async def test_a_sender_not_among_the_participants_is_named_by_their_id(
    beeper: FakeBeeperDesktop,
) -> None:
    messages = await beeper.source().recent_messages(FAMILY, limit=50)

    assert [m.source_id for m in messages] == ["wa-f-1", "wa-f-2", "wa-f-4", "wa-f-5", "wa-f-7"]
    assert messages[0].sender_name == "wa-cousin"


async def test_recent_messages_reads_no_more_than_it_needs(beeper: FakeBeeperDesktop) -> None:
    messages = await beeper.source().recent_messages(FAMILY, limit=2)

    assert [m.source_id for m in messages] == ["wa-f-5", "wa-f-7"]
    assert len(beeper.requested(f"/v1/chats/{FAMILY}/messages")) == 1
    assert not beeper.requested(f"/v1/chats/{FAMILY}")  # every sender had a name


async def test_older_messages_pages_back_from_a_messages_paging_key(
    beeper: FakeBeeperDesktop,
) -> None:
    source = beeper.source()

    older = await source.older_messages(FAMILY, before=SourceMessageRef("wa-f-4", "1004"), limit=2)
    oldest = await source.older_messages(FAMILY, before=SourceMessageRef("wa-f-1", "1001"), limit=2)

    assert [m.source_id for m in older.messages] == ["wa-f-1", "wa-f-2"]
    assert older.has_more
    assert oldest.messages == []  # only a Message without text is older
    assert not oldest.has_more
    first_page = beeper.requested(f"/v1/chats/{FAMILY}/messages")[0]
    assert dict(first_page.url.params) == {"cursor": "1004", "direction": "before"}


async def test_older_messages_without_a_message_gives_the_newest(
    beeper: FakeBeeperDesktop,
) -> None:
    older = await beeper.source().older_messages(FAMILY, before=None, limit=3)

    assert [m.source_id for m in older.messages] == ["wa-f-4", "wa-f-5", "wa-f-7"]
    assert older.has_more


async def test_older_messages_without_a_paging_key_finds_the_message_first(
    beeper: FakeBeeperDesktop,
) -> None:
    older = await beeper.source().older_messages(
        FAMILY, before=SourceMessageRef("wa-f-4", None), limit=1
    )

    assert [m.source_id for m in older.messages] == ["wa-f-2"]
    assert older.has_more


# --- new Messages ---------------------------------------------------------------------


def arrived(new: Any) -> list[tuple[str, str]]:
    return [(chat.source_id, message.source_id) for chat, message in new.messages]


async def test_new_messages_from_now_reports_nothing_already_there(
    beeper: FakeBeeperDesktop,
) -> None:
    source = beeper.source(now=fixed_clock())
    beeper.add_message(ALEX, "already-there", T0 - timedelta(seconds=30))

    start = await source.new_messages(since=None)
    later = await source.new_messages(since=start.cursor)

    assert start.messages == []
    assert later.messages == []


async def test_new_messages_are_reported_once_each_across_pages_and_polls(
    beeper: FakeBeeperDesktop,
) -> None:
    beeper.page_size = 2
    source = beeper.source(now=fixed_clock())
    start = await source.new_messages(since=None)
    beeper.add_message(ALEX, "a", T0 + timedelta(seconds=10), text="Are you free tonight?")
    beeper.add_message(FAMILY, "reaction", T0 + timedelta(seconds=15), type_="REACTION")
    beeper.add_message(FAMILY, "b", T0 + timedelta(seconds=20))
    beeper.add_message(ALEX, "c", T0 + timedelta(seconds=20), is_sender=True)
    beeper.add_message(TELEGRAM, "telegram", T0 + timedelta(seconds=25))

    first = await source.new_messages(since=start.cursor)

    assert arrived(first) == [(ALEX, "a"), (FAMILY, "b"), (ALEX, "c")]
    chat, message = first.messages[0]
    assert (chat.platform, chat.kind, chat.title) == (
        Platform.IMESSAGE,
        ChatKind.ONE_TO_ONE,
        "Alex Chen",
    )
    assert (message.text, message.sent_at, message.outbound) == (
        "Are you free tonight?",
        T0 + timedelta(seconds=10),
        False,
    )
    assert first.messages[2][1].outbound
    assert len(beeper.requested(f"/v1/chats/{ALEX}")) == 1  # each Chat looked up once a fetch

    # One more arrives at the very instant of the newest seen, one a little late.
    beeper.add_message(FAMILY, "same-instant", T0 + timedelta(seconds=20))
    beeper.add_message(ALEX, "late", T0 + timedelta(seconds=5))
    beeper.add_message(ALEX, "newest", T0 + timedelta(seconds=30))

    second = await source.new_messages(since=first.cursor)
    third = await source.new_messages(since=second.cursor)

    assert arrived(second) == [(ALEX, "late"), (FAMILY, "same-instant"), (ALEX, "newest")]
    assert third.messages == []
    assert third.cursor == second.cursor


async def test_new_messages_from_an_unrecognised_cursor_starts_from_now(
    beeper: FakeBeeperDesktop,
) -> None:
    source = beeper.source(now=fixed_clock())

    start = await source.new_messages(since="a1b2c3d4:17")  # e.g. demo mode's cursor
    beeper.add_message(ALEX, "a", T0 + timedelta(seconds=10))
    later = await source.new_messages(since=start.cursor)

    assert start.messages == []
    assert arrived(later) == [(ALEX, "a")]


# --- sending --------------------------------------------------------------------------


async def test_sending_posts_the_text_and_returns_the_pending_message_id(
    beeper: FakeBeeperDesktop,
) -> None:
    sent = await beeper.source(now=fixed_clock()).send_message(FAMILY, "See you Sunday!")

    assert (sent.source_id, sent.sent_at) == ("pending-1", T0)
    post = next(r for r in beeper.requests if r.method == "POST")
    assert post.url.path == f"/v1/chats/{FAMILY}/messages"
    assert post.headers["Authorization"] == f"Bearer {BEEPER_TOKEN}"
    assert json.loads(post.content) == {"text": "See you Sunday!"}


# --- errors ---------------------------------------------------------------------------

OPERATIONS: dict[str, Callable[[BeeperDesktopMessageSource], Any]] = {
    "list_chats": lambda s: s.list_chats(active_since=ACTIVE_SINCE),
    "recent_messages": lambda s: s.recent_messages(FAMILY, limit=5),
    "new_messages": lambda s: s.new_messages(since=None),
    "older_messages": lambda s: s.older_messages(FAMILY, before=None, limit=5),
    "send_message": lambda s: s.send_message(FAMILY, "hi"),
}


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_beeper_desktop_unreachable_makes_the_source_unavailable(
    beeper: FakeBeeperDesktop, operation: str
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    beeper.answer = refuse

    with pytest.raises(MessageSourceUnavailableError):
        await OPERATIONS[operation](beeper.source())


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_a_rejected_access_token_makes_the_source_unavailable_and_says_why(
    beeper: FakeBeeperDesktop, operation: str
) -> None:
    with pytest.raises(MessageSourceUnavailableError, match="BEEPER_ACCESS_TOKEN"):
        await OPERATIONS[operation](beeper.source(access_token="wrong"))


async def test_other_http_errors_are_raised_with_what_failed(beeper: FakeBeeperDesktop) -> None:
    beeper.answer = lambda _: httpx.Response(500, text="database is locked")

    with pytest.raises(BeeperDesktopApiError, match=r"/v1/chats/.*HTTP 500.*database is locked"):
        await beeper.source().recent_messages(FAMILY, limit=5)


# --- the app on the real adapter ------------------------------------------------------


async def test_real_mode_imports_chats_from_beeper_desktop_and_replies_through_it(
    database_url: str,
) -> None:
    # Move the fixtures so the Chats are recent enough for First Import.
    newest = max(parse(chat["lastActivity"]) for chat in load_items("chats"))
    beeper = FakeBeeperDesktop(shift=datetime.now(UTC) - timedelta(hours=1) - newest)
    app = create_app(
        make_settings(database_url, umessage_mode="real"),
        message_source=beeper.source(),
        plan_model=FakePlanModel(),
        calendar=FakeCalendar(),
        retry_seconds=RETRY_SECONDS,
    )
    async with LifespanManager(app) as manager, http_client(manager.app) as client:
        await wait_for_first_import(client)
        chats = (await client.get("/api/chats")).json()["chats"]
        family = next(chat for chat in chats if chat["title"] == "Family")
        reply = await client.post(f"/api/chats/{family['id']}/messages", json={"text": "On it"})
        sent_at = len(beeper.requests)

        async def echo_fetched() -> bool | None:
            fetched = beeper.requested("/v1/messages/search")
            return True if any(r in beeper.requests[sent_at:] for r in fetched) else None

        await eventually(echo_fetched)
        page = (await client.get(f"/api/chats/{family['id']}/messages")).json()

    server_channels = {"general", "#announcements"}
    expected = {title for _, kind, title in EXPECTED_CHATS.values()} - server_channels
    assert {chat["title"] for chat in chats} == expected
    assert reply.status_code == 201
    assert [m["text"] for m in page["messages"]] == [
        "hi all",
        "Look at this cake",
        "I'll bring dessert",
        "Sounds good",
        "Dinner at ours on Sunday at 6?",
        "On it",  # stored once, though Beeper reported it back under its final id
    ]
