"""Message Source backed by Beeper Desktop's local API (ADR-0003, proposed).

Built (#13) from the shapes in Beeper's official SDK (github.com/beeper/desktop-api-js) before
the Phase 0 spike (#2) has recorded real responses. Every mapping Phase 0 must confirm is a
named constant or function below whose docstring says so; adjust those, not the operations.

Endpoints used (all with `Authorization: Bearer <BEEPER_ACCESS_TOKEN>`):

- `GET /v1/info`: is Beeper Desktop running (and is the token accepted)?
- `GET /v1/chats/search?lastActivityAfter=` (falling back to `GET /v1/chats`) and
  `GET /v1/accounts`: the Chats, and the network of each one's account.
- `GET /v1/chats/{chatID}/messages`: a Chat's Messages, newest first, paging back with
  `cursor=<oldestCursor or a sortKey>&direction=before`.
- `GET /v1/messages/search?dateAfter=`: new Messages across all Chats, polled (no WebSocket
  is documented); `GET /v1/chats/{chatID}` for the Chat of each.
- `POST /v1/chats/{chatID}/messages {"text"}`: send; answers `{chatID, pendingMessageID}`.

Beeper Desktop not answering, or rejecting the access token (HTTP 401/403), raises
`MessageSourceUnavailableError`; any other HTTP error raises `BeeperDesktopApiError`.
"""

import json
import logging
import re
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.adapters.protocols import (
    BEEPER_DESKTOP,
    ChatKind,
    MessageSourceStatus,
    MessageSourceUnavailableError,
    NewMessages,
    OlderMessages,
    Platform,
    SentMessage,
    SourceChat,
    SourceMessage,
    SourceMessageRef,
)

logger = logging.getLogger(__name__)

Json = dict[str, Any]

STATUS_TIMEOUT_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 30.0
# Page sizes asked for; Beeper may answer with fewer. The SDK documents 1-200 for Chats; for
# Message search it documents a smaller maximum, so ask for 20 (Phase 0: confirm).
CHAT_PAGE_SIZE = 200
MESSAGE_SEARCH_PAGE_SIZE = 20
# A guard against a cursor that never ends; far more pages than one fetch should ever need.
MAX_PAGES = 500
# The sender name of the user's own Messages, as the rest of uMessage names them.
YOU = "You"

# How far back before the newest Message seen each poll for new Messages looks again, so a
# Message whose timestamp is a little older than one already seen (it reached Beeper late, or
# shares its instant) is still picked up. Ids seen within it are kept in the cursor, so none
# is reported twice. A Message that reaches Beeper later than this after its own timestamp is
# missed: Phase 0 (#2) must check how late bridged Messages arrive (and whether
# `message.upserted` push could replace polling).
NEW_MESSAGES_OVERLAP = timedelta(minutes=2)

PLATFORM_BY_NETWORK: Mapping[str, Platform] = {
    # Normalised network name (lowercase letters only) -> Platform. Phase 0 (#2) must
    # confirm the `network` names Beeper reports on Chats and accounts.
    "imessage": Platform.IMESSAGE,
    "instagram": Platform.INSTAGRAM,
    "messenger": Platform.MESSENGER,
    "facebookmessenger": Platform.MESSENGER,
    "facebook": Platform.MESSENGER,
    "whatsapp": Platform.WHATSAPP,
    "discord": Platform.DISCORD,
}

# Message `type`s that are never Messages even when they carry text (a reaction's emoji).
# Anything else with text counts, including media with a caption. Phase 0 (#2) must confirm
# the `type` values Beeper reports (the SDK lists TEXT, NOTICE, IMAGE, VIDEO, VOICE, AUDIO,
# FILE, STICKER, LOCATION, REACTION).
NON_MESSAGE_TYPES = frozenset({"REACTION", "STICKER", "NOTICE"})

# Discord group DMs hold at most 10 people, so a bigger Discord "group" is a server channel.
DISCORD_GROUP_DM_MAX_PARTICIPANTS = 10

TOKEN_REJECTED = (
    f"{BEEPER_DESKTOP} rejected the access token: set BEEPER_ACCESS_TOKEN in .env to a token "
    "created in Beeper Desktop (Settings -> Developers)"
)


class BeeperDesktopApiError(RuntimeError):
    """Beeper Desktop's API answered a request with an HTTP error (other than 401/403), or
    with something that isn't the JSON its SDK documents."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# --- mappings Phase 0 must confirm ----------------------------------------------------


def platform_for_network(network: object) -> Platform | None:
    """The Platform of a Beeper network name ("WhatsApp", "Facebook Messenger", ...), in any
    case and spacing; None for networks uMessage doesn't support (their Chats are skipped)."""
    if not isinstance(network, str):
        return None
    return PLATFORM_BY_NETWORK.get(re.sub(r"[^a-z]", "", network.casefold()))


def looks_like_discord_server_channel(chat: Json) -> bool:
    """Whether a Discord Chat Beeper calls a `group` is really a server (guild) channel.

    A HEURISTIC until Phase 0 (#2) finds how Beeper marks server channels: more participants
    than a Discord group DM can have, or a title like a channel's ("#general").
    """
    participants = chat.get("participants") or {}
    total = participants.get("total") if isinstance(participants, dict) else None
    if isinstance(total, int) and total > DISCORD_GROUP_DM_MAX_PARTICIPANTS:
        return True
    title = chat.get("title")
    return isinstance(title, str) and title.startswith("#")


def is_merged_parent(chat: Json) -> bool:
    """Whether the Chat is Beeper's merge of several Chats with one person, which holds no
    Messages itself: its members (each with `mergedIntoChatID`) are listed and used instead.

    Phase 0 (#2) must confirm that a merged parent has a `merge` field and that its member
    Chats are listed too.
    """
    return bool(chat.get("merge"))


def is_text_message(message: Json) -> bool:
    """Whether a Beeper Message item is a Message to uMessage: it has text, and isn't a
    reaction, sticker or notice (see `NON_MESSAGE_TYPES`)."""
    text = message.get("text")
    return (
        isinstance(text, str)
        and bool(text.strip())
        and message.get("type") not in NON_MESSAGE_TYPES
    )


def chat_kind(chat: Json, platform: Platform) -> ChatKind:
    """`type` "single" is one-to-one; anything else is a group, or a Discord server channel."""
    if chat.get("type") == "single":
        return ChatKind.ONE_TO_ONE
    if platform is Platform.DISCORD and looks_like_discord_server_channel(chat):
        return ChatKind.SERVER_CHANNEL
    return ChatKind.GROUP


# --- the Message Source ---------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(UTC)


class BeeperDesktopMessageSource:
    """`now` is the clock used for "now" cursors and the time a sent Message was sent."""

    def __init__(
        self,
        base_url: str,
        *,
        access_token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._base_url = base_url
        self._headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
        self._transport = transport
        self._now = now
        self._token_rejected = False

    async def status(self) -> MessageSourceStatus:
        try:
            async with self._client(timeout=STATUS_TIMEOUT_SECONDS) as client:
                response = await client.get("/v1/info")
        except httpx.TransportError:
            return MessageSourceStatus(name=BEEPER_DESKTOP, running=False)
        if response.status_code in (401, 403):
            # Running, but unusable until the token is fixed; the status can't say why.
            self._note_token_rejected()
            return MessageSourceStatus(name=BEEPER_DESKTOP, running=False)
        self._token_rejected = False
        # Any other answer (even a 404 from a version without /v1/info) means it's up.
        return MessageSourceStatus(name=BEEPER_DESKTOP, running=True)

    async def list_chats(self, *, active_since: datetime) -> list[SourceChat]:
        async with self._api() as api:
            try:
                raw_chats = await api.pages(
                    "/v1/chats/search",
                    lastActivityAfter=_iso(active_since - timedelta(seconds=1)),
                    type="any",
                    limit=CHAT_PAGE_SIZE,
                )
            except BeeperDesktopApiError:
                logger.warning("Chat search failed; listing every Chat instead", exc_info=True)
                raw_chats = await api.pages("/v1/chats", limit=CHAT_PAGE_SIZE)
            chats = _Chats(api)
            found: dict[str, SourceChat] = {}
            for raw in raw_chats:
                chat = await chats.map(raw)
                if chat is not None and chat.last_activity >= active_since:
                    found.setdefault(chat.source_id, chat)
        return list(found.values())

    async def recent_messages(self, chat_source_id: str, *, limit: int) -> list[SourceMessage]:
        return list((await self.older_messages(chat_source_id, before=None, limit=limit)).messages)

    async def older_messages(
        self, chat_source_id: str, *, before: SourceMessageRef | None, limit: int
    ) -> OlderMessages:
        """Pages back from `before`'s `paging_key` (its `sortKey`: Phase 0 (#2) must confirm a
        sortKey works as the cursor), or without one, from the newest Message until `before`
        has been passed. Oldest first."""
        if limit <= 0:
            return OlderMessages(messages=[], has_more=True)
        async with self._api() as api:
            return await _page_back(api, chat_source_id, before=before, limit=limit)

    async def new_messages(self, *, since: str | None) -> NewMessages:
        position = _NewMessagesCursor.decode(since) if since is not None else None
        from_now = position is None
        if position is None:
            position = _NewMessagesCursor(newest=self._now())
        async with self._api() as api:
            raws, included_chats = await _search_messages(
                api, after=position.newest - NEW_MESSAGES_OVERLAP
            )
            unseen = position.see(raws)
            if from_now:  # whatever Beeper already holds is now seen; nothing is reported
                return NewMessages(messages=[], cursor=position.encode())
            chats = _Chats(api, included_chats)
            found: list[tuple[SourceChat, SourceMessage]] = []
            for raw in unseen:
                if not is_text_message(raw):
                    continue
                chat = await chats.by_id(
                    str(raw.get("chatID")), fallback_activity=_timestamp(raw.get("timestamp"))
                )
                if chat is None:
                    continue
                message = _message(raw, chats.sender_names(chat.source_id))
                if message is not None:
                    found.append((chat, message))
        found.sort(key=lambda pair: pair[1].sent_at)  # stable: ties keep Beeper's order
        return NewMessages(messages=found, cursor=position.encode())

    async def send_message(self, chat_source_id: str, text: str) -> SentMessage:
        async with self._api() as api:
            answer = await api.request(
                "POST", f"/v1/chats/{_segment(chat_source_id)}/messages", json={"text": text}
            )
        pending_id = answer.get("pendingMessageID") if isinstance(answer, dict) else None
        if not isinstance(pending_id, str) or not pending_id:
            raise BeeperDesktopApiError(f"{BEEPER_DESKTOP} accepted no Message: {answer!r}")
        return SentMessage(source_id=pending_id, sent_at=self._now())

    # --- HTTP -----------------------------------------------------------------------

    def _client(self, *, timeout: float = REQUEST_TIMEOUT_SECONDS) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            transport=self._transport,
            timeout=timeout,
        )

    @asynccontextmanager
    async def _api(self) -> AsyncIterator["_Api"]:
        async with self._client() as client:
            yield _Api(client, self)

    def _note_token_rejected(self) -> None:
        if not self._token_rejected:  # say it once, not on every poll
            logger.warning(TOKEN_REJECTED)
        self._token_rejected = True


@dataclass(slots=True)
class _Api:
    """One operation's requests, mapping failures onto the Message Source's errors."""

    client: httpx.AsyncClient
    source: BeeperDesktopMessageSource

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise MessageSourceUnavailableError(
                f"{BEEPER_DESKTOP} isn't answering at {self.client.base_url}: {exc!r}"
            ) from exc
        if response.status_code in (401, 403):
            self.source._note_token_rejected()
            raise MessageSourceUnavailableError(TOKEN_REJECTED)
        if response.is_error:
            raise BeeperDesktopApiError(
                f"{BEEPER_DESKTOP} answered {method} {response.request.url.path} with HTTP "
                f"{response.status_code}: {response.text[:300]}",
                status_code=response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise BeeperDesktopApiError(
                f"{BEEPER_DESKTOP} answered {method} {path} with something that isn't JSON"
            ) from exc

    async def get(self, path: str, **params: object) -> Any:
        return await self.request(
            "GET", path, params={k: v for k, v in params.items() if v is not None}
        )

    async def page(self, path: str, **params: object) -> Json:
        answer = await self.get(path, **params)
        if not isinstance(answer, dict) or not isinstance(answer.get("items", []), list):
            raise BeeperDesktopApiError(f"{BEEPER_DESKTOP} answered {path} with no page of items")
        return answer

    async def pages(self, path: str, **params: object) -> list[Json]:
        """Every item of a paged list, following `oldestCursor` with `direction=before`."""
        items: list[Json] = []
        async for page in self.walk(path, **params):
            items.extend(_items(page))
        return items

    async def walk(self, path: str, **params: object) -> AsyncIterator[Json]:
        """The pages of a list, newest first, from `params` (which may hold a `cursor`)."""
        seen_cursors: set[str] = set()
        for _ in range(MAX_PAGES):
            page = await self.page(path, **params)
            yield page
            cursor = page.get("oldestCursor")
            if not page.get("hasMore") or not isinstance(cursor, str) or cursor in seen_cursors:
                return
            seen_cursors.add(cursor)
            params = {**params, "cursor": cursor, "direction": "before"}
        logger.warning("Stopped paging %s after %d pages", path, MAX_PAGES)


class _Chats:
    """Maps Beeper Chats onto SourceChats within one operation, looking up what it needs
    (the accounts' networks, a Chat by id) at most once."""

    def __init__(self, api: _Api, known: Mapping[str, Json] | None = None) -> None:
        self._api = api
        self._raw: dict[str, Json | None] = dict(known or {})
        self._mapped: dict[str, SourceChat | None] = {}
        self._account_networks: dict[str, str] | None = None

    async def map(
        self, raw: Json, *, fallback_activity: datetime | None = None
    ) -> SourceChat | None:
        """The SourceChat, or None for a Chat uMessage leaves out (unsupported network,
        merged parent, no id)."""
        source_id = raw.get("id")
        if not isinstance(source_id, str) or is_merged_parent(raw):
            return None
        self._raw[source_id] = raw
        # The Chat's own network decides; only a Chat without one goes by its account's.
        network = raw.get("network")
        if network is None:
            network = await self._account_network(raw.get("accountID"))
        platform = platform_for_network(network)
        last_activity = _timestamp(raw.get("lastActivity")) or fallback_activity
        if platform is None or last_activity is None:
            return None
        return SourceChat(
            source_id=source_id,
            platform=platform,
            kind=chat_kind(raw, platform),
            title=_title(raw),
            last_activity=last_activity,
        )

    async def by_id(
        self, chat_id: str, *, fallback_activity: datetime | None = None
    ) -> SourceChat | None:
        if chat_id not in self._mapped:
            raw = self._raw.get(chat_id)
            if raw is None:
                try:
                    raw = await self._api.get(f"/v1/chats/{_segment(chat_id)}")
                except BeeperDesktopApiError as exc:
                    if exc.status_code != 404:
                        raise
                    logger.warning("Beeper Desktop has no Chat %s; skipping its Messages", chat_id)
                    raw = None
            self._mapped[chat_id] = (
                await self.map(raw, fallback_activity=fallback_activity)
                if isinstance(raw, dict)
                else None
            )
        return self._mapped[chat_id]

    def sender_names(self, chat_id: str) -> dict[str, str]:
        return _participant_names(self._raw.get(chat_id) or {})

    async def _account_network(self, account_id: object) -> str | None:
        if not isinstance(account_id, str):
            return None
        if self._account_networks is None:
            answer = await self._api.get("/v1/accounts")
            accounts = answer.get("items", []) if isinstance(answer, dict) else answer
            self._account_networks = {
                str(a.get("accountID")): a.get("network")
                for a in accounts or []
                if isinstance(a, dict) and isinstance(a.get("network"), str)
            }
        return self._account_networks.get(account_id)


async def _page_back(
    api: _Api, chat_id: str, *, before: SourceMessageRef | None, limit: int
) -> OlderMessages:
    path = f"/v1/chats/{_segment(chat_id)}/messages"
    params: dict[str, object] = {}
    if before is not None and before.paging_key is not None:
        params = {"cursor": before.paging_key, "direction": "before"}
    passed_before = before is None or before.paging_key is not None
    names: dict[str, str] | None = None
    collected: list[SourceMessage] = []  # newest first
    has_more = False
    async for page in api.walk(path, **params):
        for raw in _items(page):
            if not passed_before:
                passed_before = raw.get("id") == before.source_id  # type: ignore[union-attr]
                continue
            if before is not None and raw.get("id") == before.source_id:
                continue  # in case the cursor is inclusive
            if not is_text_message(raw):
                continue
            if names is None and _needs_participants(raw):
                names = _participant_names(await api.get(f"/v1/chats/{_segment(chat_id)}"))
            message = _message(raw, names or {})
            if message is not None:
                collected.append(message)
        has_more = bool(page.get("hasMore"))
        if len(collected) >= limit:
            break
    if not passed_before:
        raise BeeperDesktopApiError(
            f"{BEEPER_DESKTOP} has no Message {before.source_id} in Chat {chat_id} to page "  # type: ignore[union-attr]
            "back from"
        )
    return OlderMessages(
        messages=collected[:limit][::-1], has_more=has_more or len(collected) > limit
    )


async def _search_messages(api: _Api, *, after: datetime) -> tuple[list[Json], dict[str, Json]]:
    """Every Message Beeper has with a timestamp after `after`, oldest first, plus the Chats
    the answers included (if Beeper includes them)."""
    newest_first: list[Json] = []
    chats: dict[str, Json] = {}
    async for page in api.walk(
        "/v1/messages/search", dateAfter=_iso(after), limit=MESSAGE_SEARCH_PAGE_SIZE
    ):
        newest_first.extend(_items(page))
        included = page.get("chats")
        if isinstance(included, dict):
            chats.update({k: v for k, v in included.items() if isinstance(v, dict)})
    return newest_first[::-1], chats


@dataclass(slots=True)
class _NewMessagesCursor:
    """Where polling for new Messages resumes: the newest Message timestamp seen, and the
    Messages seen within `NEW_MESSAGES_OVERLAP` of it, so none of them is reported twice."""

    newest: datetime
    seen: dict[tuple[str, str], datetime] = field(default_factory=dict)

    VERSION = 1

    @classmethod
    def decode(cls, cursor: str) -> "_NewMessagesCursor | None":
        """None for a cursor this adapter didn't make (e.g. demo mode's): start from now."""
        try:
            data = json.loads(cursor)
            if data.get("v") != cls.VERSION:
                return None
            newest = _timestamp(data["newest"])
            seen = {(str(c), str(m)): _timestamp(t) for c, m, t in data["seen"]}
        except (ValueError, TypeError, KeyError, AttributeError):
            return None
        if newest is None or None in seen.values():
            return None
        return cls(newest=newest, seen=seen)  # type: ignore[arg-type]

    def encode(self) -> str:
        cutoff = self.newest - NEW_MESSAGES_OVERLAP
        seen = sorted((t, c, m) for (c, m), t in self.seen.items() if t > cutoff)
        return json.dumps(
            {
                "v": self.VERSION,
                "newest": _iso(self.newest),
                "seen": [[c, m, _iso(t)] for t, c, m in seen],
            },
            separators=(",", ":"),
        )

    def see(self, raws: Iterable[Json]) -> list[Json]:
        """Mark Messages seen; returns those not seen before (with a timestamp), in order."""
        unseen: list[Json] = []
        for raw in raws:
            sent_at = _timestamp(raw.get("timestamp"))
            key = (str(raw.get("chatID")), str(raw.get("id")))
            if sent_at is None or key in self.seen:
                continue
            self.seen[key] = sent_at
            self.newest = max(self.newest, sent_at)
            unseen.append(raw)
        return unseen


# --- small helpers --------------------------------------------------------------------


def _items(page: Json) -> list[Json]:
    return [item for item in page.get("items") or [] if isinstance(item, dict)]


def _message(raw: Json, names: Mapping[str, str]) -> SourceMessage | None:
    """A text Message item as a SourceMessage; None if it lacks an id or timestamp."""
    source_id, sent_at = raw.get("id"), _timestamp(raw.get("timestamp"))
    if not isinstance(source_id, str) or sent_at is None:
        return None
    outbound = raw.get("isSender") is True
    sort_key = raw.get("sortKey")
    return SourceMessage(
        source_id=source_id,
        sender_name=YOU if outbound else _sender_name(raw, names),
        sent_at=sent_at,
        text=str(raw.get("text")),
        outbound=outbound,
        paging_key=str(sort_key) if sort_key is not None else None,
    )


def _sender_name(raw: Json, names: Mapping[str, str]) -> str:
    """`senderName` if Beeper gives it, else the participant's `fullName`, else `senderID`."""
    name = raw.get("senderName")
    if isinstance(name, str) and name.strip():
        return name
    sender_id = str(raw.get("senderID") or "")
    return names.get(sender_id) or sender_id or "Unknown"


def _needs_participants(raw: Json) -> bool:
    name = raw.get("senderName")
    return raw.get("isSender") is not True and not (isinstance(name, str) and name.strip())


def _participant_names(chat: Json) -> dict[str, str]:
    participants = chat.get("participants") or {}
    users = participants.get("items", []) if isinstance(participants, dict) else participants
    names: dict[str, str] = {}
    for user in users or []:
        if isinstance(user, dict) and isinstance(user.get("id"), str):
            name = user.get("fullName") or user.get("username")
            if isinstance(name, str) and name.strip():
                names[user["id"]] = name
    return names


def _title(chat: Json) -> str:
    """The Chat's title; untitled, the names of the other participants."""
    title = chat.get("title")
    if isinstance(title, str) and title.strip():
        return title
    participants = chat.get("participants") or {}
    users = participants.get("items", []) if isinstance(participants, dict) else []
    others = [
        str(u.get("fullName") or u.get("username"))
        for u in users
        if isinstance(u, dict) and not u.get("isSelf") and (u.get("fullName") or u.get("username"))
    ]
    return ", ".join(others) or str(chat.get("id"))


def _timestamp(value: object) -> datetime | None:
    """An ISO 8601 timestamp as an aware datetime (UTC if it has no offset)."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _segment(value: str) -> str:
    """A Chat id as one URL path segment, encoded like the SDK's `encodeURIComponent`."""
    return quote(value, safe="!'()*")
