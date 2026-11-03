# Implementation Plan: Unified Inbox & Calendar Extractor

## Workflow Instructions for Claude Code
Execute **one phase at a time**. For the active phase:
1. Write unit/integration tests for the target module first (TDD).
2. Implement the listed files to satisfy the tests.
3. Run the phase's **Verification Gate** commands until 100% pass.
4. Check off completed items (`[x]`) in this `PLAN.md` file and stop so the user can review and commit.

### Rules that apply to every phase
- Every Verification Gate implicitly includes `cd backend && uv run ruff check . && uv run ruff format --check .` (backend phases).
- Unit tests never call Gemini, Google Calendar or a real homeserver: mock them. Tests that need real services are marked `@pytest.mark.integration` or `@pytest.mark.live` and are excluded from the default run.
- Tests run against a separate database (`TEST_DATABASE_URL`), never the dev database.
- Never commit `.env`, `token.json`, `credentials.json` or the Matrix crypto store.

---

## Phase 0: Matrix / Beeper Feasibility Spike
**Goal:** Prove we can read (and decrypt) a real bridged message from the target account before building ingestion on top of it. The outcome decides how Phase 2 connects.

### Files to Create/Modify
- `backend/scripts/matrix_spike.py`
- `docs/matrix-spike.md`

### Tasks
- [ ] Write a throwaway `matrix-nio` script that logs in to the target homeserver (Beeper), persists a device + crypto store, syncs once, and prints the last few events from one bridged room (e.g. WhatsApp).
- [ ] Determine whether bridged rooms are end-to-end encrypted, and whether the script can decrypt `MegolmEvent`s (device verification / key sharing / `matrix-nio[e2e]` + libolm).
- [ ] Inspect room state for bridge metadata (`m.bridge` / `uk.half-shot.bridge` events, bridge bot user IDs) to confirm how platform detection will work.
- [ ] Check for any terms/ban warnings on third-party client logins.
- [ ] Record findings and the chosen approach in `docs/matrix-spike.md`. If direct Beeper access is not viable, document the fallback (e.g. self-hosted bridges on our own homeserver, or another Beeper-supported API) and update Phase 2 before starting it.

### Verification Gate
- [ ] `docs/matrix-spike.md` shows one decrypted bridged message body (redacted) and names the connection approach for Phase 2.
- [ ] User has reviewed and approved the approach.

---

## Phase 1: Infrastructure, Backend Scaffold & Database Schema
**Goal:** Spin up PostgreSQL via Docker, scaffold the FastAPI backend, define the schema with SQLAlchemy 2.0 (async) and apply it with Alembic.

### Files to Create/Modify
- `docker-compose.yml`
- `.env.example`
- `.gitignore`
- `backend/pyproject.toml`
- `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/0001_initial.py`
- `backend/app/config.py`
- `backend/app/db.py`
- `backend/app/models.py`
- `backend/app/main.py`
- `backend/tests/conftest.py`
- `backend/tests/test_health.py`

### Tasks
- [ ] Create `docker-compose.yml` with PostgreSQL 16 (port 5432, healthcheck) and an init script that creates both the dev and test databases.
- [ ] Initialize `backend/` (managed with `uv`) with FastAPI, Uvicorn, SQLAlchemy 2.0 (asyncio), `asyncpg`, Alembic, `matrix-nio` (with `[e2e]` if Phase 0 requires it), `google-genai`, `google-api-python-client`, `google-auth-oauthlib`, `pydantic-settings`; dev deps `pytest`, `pytest-asyncio`, `httpx`, `ruff`.
- [ ] Implement `config.py` settings: `DATABASE_URL`, `TEST_DATABASE_URL`, `MATRIX_HOMESERVER`, `MATRIX_USER_ID`, `MATRIX_PASSWORD`/`MATRIX_ACCESS_TOKEN`, `MATRIX_STORE_PATH`, `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-3.5-flash`; check current availability when implementing), `USER_TIMEZONE`, `EXTRACT_CONFIDENCE_THRESHOLD` (0.50), `EXTRACT_DEBOUNCE_SECONDS` (60), `EXTRACT_MAX_MESSAGE_AGE_MINUTES`, `API_TOKEN`, `CORS_ORIGINS`, `GOOGLE_TOKEN_PATH`.
- [ ] Implement `models.py`:
  - Enums `Platform` (`WHATSAPP`, `MESSENGER`, `INSTAGRAM`, `DISCORD`, `IMESSAGE`, `SIGNAL`, `TELEGRAM`, `SLACK`, `MATRIX`, `UNKNOWN`) and `EventStatus` (`PENDING_REVIEW`, `CONFIRMED`, `DISMISSED`).
  - `Room` (matrix_room_id unique, name, platform, last_message_at).
  - `Message` (matrix_event_id unique, room FK, sender_id, sender_name, body, msgtype, is_outbound, sent_at timestamptz, edited_at, redacted).
  - `DetectedEvent` (room FK, source_message FK, title, start_time/end_time timestamptz, all_day, timezone, location, confidence, status, calendar_event_id unique nullable, created_at/updated_at).
  - `SyncState` (single row: Matrix `next_batch` token).
- [ ] Write the initial Alembic migration and apply it.
- [ ] Create FastAPI entrypoint (`main.py`) with lifespan DB engine setup/teardown, CORS from `CORS_ORIGINS`, a bearer-token dependency checking `API_TOKEN` (applied to all `/api/*` routes except health), and `GET /api/health` (reports DB connectivity).
- [ ] API JSON uses camelCase (Pydantic alias generator); DB columns stay snake_case.

### Verification Gate
- [ ] `docker compose up -d db` succeeds and DB is healthy.
- [ ] `cd backend && uv run alembic upgrade head` succeeds against the dev DB.
- [ ] `cd backend && uv run pytest tests/test_health.py` passes (incl. a 401 check for a protected route without a token).

---

## Phase 2: Matrix Ingestion Service & WebSocket Broadcast
**Goal:** Connect `matrix-nio` using the approach chosen in Phase 0, persist room messages to PostgreSQL, and broadcast live events over a FastAPI WebSocket.

### Files to Create/Modify
- `docker-compose.yml` (add a local Conduit-family homeserver for integration tests)
- `backend/app/ws_manager.py`
- `backend/app/matrix_listener.py`
- `backend/app/platforms.py`
- `backend/app/routers/rooms.py`
- `backend/app/main.py` (start/stop listener, mount `/ws`, include routers)
- `backend/tests/test_matrix_ingest.py`
- `backend/tests/test_rooms_api.py`

### Tasks
- [ ] Build `ConnectionManager` in `ws_manager.py` to broadcast `NEW_MESSAGE` and `EVENT_DETECTED` JSON payloads; expose `GET /ws` in `main.py` (token checked via query param), with a ping/heartbeat.
- [ ] Build `platforms.py`: map a room to `Platform` from bridge state events (`m.bridge` / `uk.half-shot.bridge` protocol id) with fallback to bridge bot user-ID patterns; unit-test with fixture state.
- [ ] Build `matrix_listener.py` using `AsyncClient`:
  - Persist device ID and crypto store under `MATRIX_STORE_PATH`; handle encrypted rooms per Phase 0 findings (log undecryptable events, request keys).
  - Load/save the `next_batch` token in `SyncState` so restarts resume instead of re-reading history.
  - Upsert `Room` and insert `Message` on text events, deduplicating via `matrix_event_id`; set `is_outbound` when the sender is our own user.
  - Handle edits (`m.replace`: update body + `edited_at`, don't insert) and redactions (mark `redacted`); store non-text messages as a placeholder body with their `msgtype`.
  - Broadcast `NEW_MESSAGE` after each insert.
  - Provide `send_room_message(matrix_room_id, body)` that stores the outbound message using the event ID returned by `room_send`, so the sync echo is deduplicated.
  - Run as a single long-lived task started in the lifespan (keep a reference; cancel cleanly on shutdown). The app must run with one worker.
- [ ] Create `routers/rooms.py`:
  - `GET /api/rooms` (filterable by `platform`, sorted by `lastMessageAt` desc).
  - `GET /api/rooms/{id}/messages` (cursor pagination via `before`; `around=<messageId>` for deep links; includes linked `detectedEvent`).
  - `POST /api/rooms/{id}/reply` (sends via Matrix and returns the stored outbound message).
- [ ] Write `test_matrix_ingest.py` with mocked nio event objects: persistence, duplicate protection, outbound-echo dedup, edits, redactions, sync-token persistence.
- [ ] Write `test_rooms_api.py`: filtering, ordering, pagination, `around`, reply.
- [ ] Optional `@pytest.mark.integration` test against the local homeserver: send a message, see it ingested.

### Verification Gate
- [ ] `cd backend && uv run pytest tests/test_matrix_ingest.py tests/test_rooms_api.py -v` passes.
- [ ] `cd backend && uv run ruff check .` passes with zero errors.

---

## Phase 3: Two-Stage AI Event Extractor (Regex + Debounced Context + Gemini)
**Goal:** Detect event intent in incoming messages, wait for the conversation to settle, send the last 5 messages to Gemini with the right date/time reference, and create or update one pending event per conversation.

### Files to Create/Modify
- `backend/app/extractor.py`
- `backend/app/matrix_listener.py` (hook)
- `backend/tests/test_extractor.py`
- `backend/tests/fixtures/chats/*.json` (live eval cases)
- `backend/tests/test_extractor_live.py`

### Tasks
- [ ] Implement `should_run_extractor(body: str) -> bool` using compiled regex for days, times, relative dates and activity keywords.
- [ ] Implement recency guard: skip extraction for messages older than `EXTRACT_MAX_MESSAGE_AGE_MINUTES` (protects against backfill/initial sync) and for redacted messages.
- [ ] Implement a per-room debounce scheduler: a regex hit schedules extraction for the room `EXTRACT_DEBOUNCE_SECONDS` after its latest message; new messages reset the timer. Limit concurrent Gemini calls with a semaphore.
- [ ] Implement `fetch_room_context(room_id, limit=5)` formatting the last 5 messages with sender names and ISO timestamps in `USER_TIMEZONE`.
- [ ] Implement `extract_event_from_context()` calling `GEMINI_MODEL` with Pydantic structured output (`ExtractedEventSchema`: `is_event`, `title`, `start_time`, `end_time`, `all_day`, `location`, `confidence`). The prompt includes the source message timestamp and `USER_TIMEZONE` so relative dates ("Friday") resolve correctly. Default duration (e.g. 1h) when no end time is given.
- [ ] Implement routing:
  - Ignore if `is_event == False` or `confidence < EXTRACT_CONFIDENCE_THRESHOLD`.
  - If the room already has a `PENDING_REVIEW` event created recently, update it (and re-anchor to the newest source message) instead of creating a duplicate.
  - Otherwise create `DetectedEvent` (`PENDING_REVIEW`).
  - Broadcast `EVENT_DETECTED` (create or update).
- [ ] Hook the scheduler into `matrix_listener.py` without blocking the sync loop; log and swallow Gemini errors.
- [ ] Unit tests (Gemini mocked) in `test_extractor.py`: regex positives/negatives, recency guard, debounce collapsing the multi-turn thread (Msg 1: "Dinner Friday?", Msg 2: "Keen", Msg 3: "7:30pm at Chaco Bar") into **one** extraction and **one** event, update-instead-of-duplicate, threshold routing, timezone handling, casual non-event messages.
- [ ] `@pytest.mark.live` eval in `test_extractor_live.py` over the chat fixtures against the real model (run manually; reports accuracy, not part of the default gate).

### Verification Gate
- [ ] `cd backend && uv run pytest tests/test_extractor.py -v` passes.
- [ ] (Manual, optional) `cd backend && uv run pytest -m live tests/test_extractor_live.py` reviewed by the user.

---

## Phase 4: Google Calendar Sync & Events REST API
**Goal:** Allow confirming (with edits) or dismissing detected events and syncing confirmed events to the user's primary Google Calendar.

### Files to Create/Modify
- `backend/scripts/google_auth.py`
- `backend/app/gcal_service.py`
- `backend/app/routers/events.py`
- `backend/tests/test_events_api.py`

### Tasks
- [ ] `scripts/google_auth.py`: one-time local OAuth flow (`InstalledAppFlow`, scope `calendar.events`) that writes `token.json` to `GOOGLE_TOKEN_PATH`; document mounting it into the container.
- [ ] `gcal_service.py`: load/refresh credentials (persist refreshed token), and `create_calendar_event(event) -> str` returning the Google event ID. Send `timeZone`, handle all-day events (`date` vs `dateTime`), include a link/quote of the source chat in the description. Run the sync Google client via `asyncio.to_thread`.
- [ ] Create `routers/events.py`:
  - `GET /api/events?status=PENDING_REVIEW|CONFIRMED&roomId=...&from=...` (sorted by `startTime`).
  - `POST /api/events/{id}/confirm`: accepts optional overrides for `title`, `startTime`, `endTime`, `allDay`, `location`. Only allowed from `PENDING_REVIEW` (409 otherwise). Lock the row, call `gcal_service`, then set `CONFIRMED` and save `calendarEventId`. If the Google call fails, the status stays `PENDING_REVIEW` and the API returns 502. Repeated confirms never create a second calendar event.
  - `POST /api/events/{id}/dismiss`: `PENDING_REVIEW` → `DISMISSED` (409 otherwise).
- [ ] Write `test_events_api.py` mocking the Google client: state transitions, overrides, payload formatting (timed + all-day, time zone), idempotent double-confirm, Google failure rollback, `roomId` filter.

### Verification Gate
- [ ] `cd backend && uv run pytest tests/test_events_api.py -v` passes.

---

## Phase 5: Next.js Unified Inbox & Events Dashboard
**Goal:** Build the multi-platform chat interface with inline event banners and the Events Review & Agenda page.

### Files to Create/Modify
- `frontend/package.json` (incl. `"type-check": "tsc --noEmit"`)
- `frontend/src/lib/api.ts`
- `frontend/src/lib/ws.ts`
- `frontend/src/components/SidebarNav.tsx`
- `frontend/src/components/PlatformFilterPills.tsx`
- `frontend/src/components/ChatThread.tsx`
- `frontend/src/components/InlineEventBanner.tsx`
- `frontend/src/components/EventEditModal.tsx`
- `frontend/src/app/inbox/page.tsx`
- `frontend/src/app/events/page.tsx`

### Tasks
- [ ] Initialize Next.js App Router project with TypeScript and Tailwind CSS in `frontend/`; add the `type-check` script. API base URL and token come from env (`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_API_TOKEN`; local-only use).
- [ ] Create typed API helpers (`api.ts`, types mirroring the backend's camelCase JSON) and a reconnecting WebSocket hook (`ws.ts`) that updates local state on `NEW_MESSAGE` and `EVENT_DETECTED` (create and update), and refetches after reconnect.
- [ ] Build `/inbox`:
  - Left column: platform filter pills + room list sorted by last message, with platform badges.
  - Center column: message history (load older via cursor), reply input bar, and `InlineEventBanner` beneath messages that anchor a `DetectedEvent`, with `[Add to Calendar]` and `[Dismiss]`.
  - Right drawer: upcoming events for the active room (`GET /api/events?roomId=`).
  - Supports deep links `/inbox?room=<id>&message=<id>` (uses `around=` and scrolls to/highlights the message).
- [ ] Build `/events`:
  - Top: **Pending Review Queue** cards with source chat quote, platform badge, extracted date/time/location, `EventEditModal`, and `[Approve & Sync]` / `[Dismiss]` (buttons disabled while in flight; show API errors).
  - Bottom: **Confirmed Upcoming Agenda** with a deep link back to the source message in `/inbox`.
- [ ] Keep every component under 200 lines.

### Verification Gate
- [ ] `cd frontend && npm run type-check && npm run lint && npm run build` completes with zero errors.
