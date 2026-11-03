# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "websockets>=13"]
# ///
"""Phase 0 spike (booblewail/uMessage#2): can Beeper Desktop's local API be uMessage's Message Source?

Run on your Mac with Beeper Desktop open and its API enabled (Beeper Desktop settings -> Developers / API):

    export BEEPER_ACCESS_TOKEN=...          # token created in Beeper Desktop
    uv run backend/scripts/beeper_spike.py  # read-only checks
    uv run backend/scripts/beeper_spike.py --send-to <chatID>   # also send one test Message

It prints a report and writes REDACTED recorded responses to backend/tests/fixtures/beeper/ plus a
findings draft to docs/beeper-spike-output.md. Message text, names and titles are replaced by
"<redacted N chars>" and digits in ids are masked, but review the files before sharing them.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "beeper"
REPORT = ROOT / "docs" / "beeper-spike-output.md"

TEXT_KEYS = {
    "text", "title", "fullName", "username", "displayName", "name", "description",
    "phoneNumber", "email", "imgURL", "avatarURL", "srcURL", "fileName", "linkedMessage",
}
KEEP_KEYS = {
    "type", "network", "timestamp", "lastActivity", "isSender", "isSelf", "hasMore",
    "direction", "isArchived", "isMuted", "isPinned", "isReadOnly", "unreadCount", "total",
    "mimeType", "dateAfter", "dateBefore", "version", "platform",
}

lines: list[str] = []


def out(s: str = "") -> None:
    print(s)
    lines.append(s)


def redact(value, key: str | None = None):
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    if isinstance(value, str):
        if key in TEXT_KEYS:
            return f"<redacted {len(value)} chars>"
        if key in KEEP_KEYS:
            return value
        return pseudonymise(value)  # hides phone numbers inside ids, keeps ids distinct
    return value


def pseudonymise(value: str) -> str:
    """Replace every digit with one derived from a hash of the whole string.

    Deterministic (the same id maps the same way in every file), structure-preserving,
    and distinct ids stay distinct, so recorded fixtures still work for de-duplication tests.
    """
    if not any(ch.isdigit() for ch in value):
        return value
    digest = hashlib.sha256(value.encode()).hexdigest()
    hash_digits = iter(str(int(digest, 16)))
    return re.sub(r"\d", lambda _: next(hash_digits), value)


def save(name: str, data) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / f"{name}.json").write_text(json.dumps(redact(data), indent=2, ensure_ascii=False))


async def get(client: httpx.AsyncClient, path: str, fixture: str | None = None, **params):
    clean = {k: v for k, v in params.items() if v is not None}
    try:
        r = await client.get(path, params=clean)
    except httpx.HTTPError as e:
        out(f"  ! GET {path} failed: {e!r}")
        return None
    if r.status_code >= 400:
        out(f"  ! GET {path} {clean} -> HTTP {r.status_code}: {r.text[:200]}")
        return None
    data = r.json()
    if fixture:
        save(fixture, data)
    return data


def keys_of(items: list[dict]) -> list[str]:
    return sorted({k for it in items for k in it})


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("BEEPER_BASE_URL", "http://localhost:23373"))
    ap.add_argument("--send-to", metavar="CHAT_ID", help="send one test Message to this Chat")
    ap.add_argument("--ws-seconds", type=int, default=30, help="how long to listen on the WebSocket")
    args = ap.parse_args()

    token = os.environ.get("BEEPER_ACCESS_TOKEN")
    if not token:
        print("Set BEEPER_ACCESS_TOKEN (create one in Beeper Desktop's API settings).")
        return 2
    headers = {"Authorization": f"Bearer {token}"}

    out(f"# Beeper Desktop API spike output ({datetime.now(UTC).isoformat(timespec='seconds')})")
    out(f"\nBase URL: `{args.base_url}`\n")

    async with httpx.AsyncClient(base_url=args.base_url, headers=headers, timeout=20) as client:
        # 1. Reachability and info
        out("## 1. Info")
        info = await get(client, "/v1/info", "info")
        if info is None:
            out("Beeper Desktop API not reachable. Is Beeper Desktop open with the API enabled?")
            REPORT.write_text("\n".join(lines))
            return 1
        out(f"Info keys: {sorted(info)}")

        # 2. Accounts = Platforms
        out("\n## 2. Accounts (how Platforms are identified)")
        accounts = await get(client, "/v1/accounts", "accounts")
        acc_items = accounts if isinstance(accounts, list) else (accounts or {}).get("items", [])
        out(f"Account keys: {keys_of(acc_items)}")
        for a in acc_items:
            out(f"- accountID `{redact(a.get('accountID') or a.get('id'))}` network={a.get('network')!r}")

        # 3. Chats
        out("\n## 3. Chats")
        chats_page = await get(client, "/v1/chats", "chats_list", limit=200)
        chats = (chats_page or {}).get("items", [])
        out(f"Fetched {len(chats)} Chats (hasMore={(chats_page or {}).get('hasMore')}). Keys: {keys_of(chats)}")
        by_net: dict[str, list[dict]] = defaultdict(list)
        for c in chats:
            by_net[str(c.get("network"))].append(c)
        for net, cs in sorted(by_net.items()):
            types = Counter(c.get("type") for c in cs)
            sizes = sorted((c.get("participants") or {}).get("total") or 0 for c in cs)
            out(f"- {net}: {len(cs)} Chats, types={dict(types)}, participant totals={sizes[:5]}…{sizes[-5:]}")
        out("\nLook at the Discord rows: which keys or values tell server channels apart from DMs / group DMs?")
        for c in by_net.get("Discord", [])[:10]:
            sample = {k: c.get(k) for k in ("type", "isReadOnly", "isMuted") if k in c}
            extra = sorted(set(c) - {"id", "title", "participants", "preview"})
            out(f"  Discord Chat: {sample} participants={(c.get('participants') or {}).get('total')} keys={extra}")

        # 4. Messages per Platform: read, page back, page forward
        out("\n## 4. Messages per Platform")
        for net, cs in sorted(by_net.items()):
            chat = max(cs, key=lambda c: c.get("lastActivity") or "")
            cid = chat["id"]
            slug = re.sub(r"\W+", "_", net.lower())
            page = await get(client, f"/v1/chats/{cid}/messages", f"messages_{slug}")
            if not page:
                continue
            items = page.get("items", [])
            out(f"### {net}: Chat `{redact(cid)}` ({chat.get('type')})")
            out(f"- first page: {len(items)} Messages, hasMore={page.get('hasMore')}, keys={keys_of(items)}")
            out(f"- types={dict(Counter(m.get('type') for m in items))}, isSender={dict(Counter(m.get('isSender') for m in items))}")
            if items:
                ts = [m.get("timestamp") for m in items]
                out(f"- order: first={ts[0]} last={ts[-1]} (newest first?)")
            older = await get(
                client, f"/v1/chats/{cid}/messages", f"messages_{slug}_older",
                cursor=page.get("oldestCursor"), direction="before",
            )
            if older is not None:
                ids = {m.get("id") for m in items}
                overlap = sum(1 for m in older.get("items", []) if m.get("id") in ids)
                out(f"- page back (direction=before): {len(older.get('items', []))} Messages, overlap={overlap}")
            newer = await get(
                client, f"/v1/chats/{cid}/messages", f"messages_{slug}_newer",
                cursor=page.get("newestCursor"), direction="after",
            )
            if newer is not None:
                out(f"- page forward (direction=after from newest): {len(newer.get('items', []))} Messages (expect 0)")

        # 5. "New since" across all Chats
        out("\n## 5. New Messages since a time (polling option)")
        since = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
        recent = await get(client, "/v1/messages/search", "messages_search_recent", dateAfter=since, limit=50)
        if recent is not None:
            r_items = recent.get("items", [])
            out(f"/v1/messages/search?dateAfter=30min ago -> {len(r_items)} Messages, hasMore={recent.get('hasMore')}")
            out(f"Networks covered: {dict(Counter(str(m.get('accountID'))[:12] for m in r_items))}")

        # 6. Send (optional)
        if args.send_to:
            out("\n## 6. Send a test Message")
            r = await client.post(f"/v1/chats/{args.send_to}/messages", json={"text": "uMessage spike test ✅"})
            out(f"POST -> HTTP {r.status_code}")
            if r.status_code < 400:
                sent = r.json()
                save("send_response", sent)
                out(f"Send response keys: {sorted(sent)}")
                await asyncio.sleep(3)
                pending = sent.get("pendingMessageID")
                if pending:
                    msg = await get(client, f"/v1/chats/{sent.get('chatID', args.send_to)}/messages/{pending}", "sent_message")
                    out(f"GET by pendingMessageID -> {redact(msg) if msg else 'not found'}")
                latest = await get(client, f"/v1/chats/{args.send_to}/messages", "after_send_messages")
                if latest and latest.get("items"):
                    m = latest["items"][0]
                    out(f"Newest Message after send: id={redact(m.get('id'))} isSender={m.get('isSender')} (same as pending id? {m.get('id') == pending})")

    # 7. WebSocket push (path is undocumented; try a few)
    out("\n## 7. WebSocket push")
    ws_base = args.base_url.replace("http", "ws", 1)
    for path in ("/v1/ws", "/v1/events", "/ws", "/v1/websocket"):
        try:
            async with websockets.connect(ws_base + path, additional_headers=headers, open_timeout=5) as ws:
                out(f"Connected to {path}. Listening {args.ws_seconds}s; send yourself a Message from your phone now…")
                seen: Counter[str] = Counter()
                samples = []
                try:
                    async with asyncio.timeout(args.ws_seconds):
                        async for raw in ws:
                            try:
                                evt = json.loads(raw)
                            except ValueError:
                                evt = {"raw": str(raw)[:200]}
                            seen[str(evt.get("type") or evt.get("event") or "?")] += 1
                            if len(samples) < 10:
                                samples.append(evt)
                except TimeoutError:
                    pass
                save("ws_events", samples)
                out(f"Event types seen: {dict(seen) or 'none'}")
                break
        except Exception as e:  # noqa: BLE001 - spike: report any failure
            out(f"{path}: {type(e).__name__}: {str(e)[:120]}")

    out("\n## Done\nFixtures: backend/tests/fixtures/beeper/  ·  Review them before sharing.")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")
    print(f"\nWrote {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
