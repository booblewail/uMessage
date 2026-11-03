# Implementation Plan: Unified Inbox & Calendar Extractor

## Workflow Instructions for Claude Code
Execute **one phase at a time**. For the active phase:
1. Write unit/integration tests for the target module first (TDD).
2. Implement the listed files to satisfy the tests.
3. Run the phase's **Verification Gate** commands until 100% pass.
4. Check off completed items (`[x]`) in this `PLAN.md` file and stop so the user can review and commit.

---

## Phase 1: Infrastructure, Monorepo Scaffold & Database Schema
**Goal:** Spin up PostgreSQL via Docker, configure Python/FastAPI and Next.js workspaces, and apply the Prisma schema.

### Files to Create/Modify
- `docker-compose.yml`
- `.env.example`
- `backend/pyproject.toml`
- `backend/prisma/schema.prisma`
- `backend/app/config.py`
- `backend/app/main.py`
- `backend/tests/test_health.py`

### Tasks
- [ ] Create `docker-compose.yml` with PostgreSQL 16 (port 5432) and healthcheck.
- [ ] Initialize `backend/` with FastAPI, Uvicorn, `prisma`, `matrix-nio`, `google-genai`, `google-api-python-client`, `pydantic-settings`, `pytest`, and `pytest-asyncio`.
- [ ] Implement `backend/prisma/schema.prisma` with `Platform` enum, `EventStatus` enum, and `Room`, `Message`, and `DetectedEvent` models.
- [ ] Generate Prisma Python client and run initial migration.
- [ ] Create FastAPI entrypoint (`backend/app/main.py`) with lifespan DB connection and `GET /api/health` endpoint.

### Verification Gate
- [ ] `docker compose up -d db` succeeds and DB is healthy.
- [ ] `cd backend && prisma validate && prisma db push` succeeds.
- [ ] `cd backend && pytest tests/test_health.py` passes.

---

## Phase 2: Matrix Ingestion Service & WebSocket Broadcast
**Goal:** Connect `matrix-nio` to the Matrix homeserver, persist incoming room messages to PostgreSQL, and broadcast live events over FastAPI WebSockets.

### Files to Create/Modify
- `backend/app/ws_manager.py`
- `backend/app/matrix_listener.py`
- `backend/app/routers/rooms.py`
- `backend/tests/test_matrix_ingest.py`

### Tasks
- [ ] Build `ConnectionManager` in `ws_manager.py` to broadcast `NEW_MESSAGE` and `EVENT_DETECTED` JSON payloads to connected frontend clients.
- [ ] Build `matrix_listener.py` using `AsyncClient` from `matrix-nio`:
  - Map bridged room state/names to the `Platform` enum (`WHATSAPP`, `MESSENGER`, `DISCORD`, `IMESSAGE`, etc.).
  - Upsert `Room` and insert `Message` records on `RoomMessageText` events (deduplicating via `matrixEventId`).
  - Provide `send_room_message(matrix_room_id, body)` helper for two-way replies.
- [ ] Create `routers/rooms.py` with:
  - `GET /api/rooms` (filterable by `platform`, sorted by `lastMessageAt` desc).
  - `GET /api/rooms/{id}/messages` (paginated, includes linked `detectedEvent`).
  - `POST /api/rooms/{id}/reply` (sends message via Matrix and stores outbound message).
- [ ] Write `test_matrix_ingest.py` using mocked `RoomMessageText` payloads to verify DB persistence and duplicate protection.

### Verification Gate
- [ ] `cd backend && pytest tests/test_matrix_ingest.py -v` passes.
- [ ] `cd backend && ruff check .` passes with zero errors.

---

## Phase 3: Two-Stage AI Event Extractor (Regex + 5-Message Context + Gemini)
**Goal:** Detect temporal/event intent in incoming messages, fetch the last 5 messages in the room for multi-turn context, and extract structured event JSON.

### Files to Create/Modify
- `backend/app/extractor.py`
- `backend/tests/test_extractor.py`

### Tasks
- [ ] Implement `should_run_extractor(body: str) -> bool` using compiled regex for days, times, relative dates, and activity keywords.
- [ ] Implement `fetch_room_context(room_id: str, limit: int = 5)` to format the last 5 messages with sender names and ISO timestamps.
- [ ] Implement `extract_event_from_context()` calling `gemini-2.5-flash` with Pydantic structured output (`ExtractedEventSchema`).
- [ ] Implement confidence routing:
  - Ignore if `is_event == False` or `confidence < 0.50`.
  - Save to `DetectedEvent` (`status = PENDING_REVIEW`) and broadcast `EVENT_DETECTED` via WebSocket if `confidence >= 0.50`.
- [ ] Hook `extractor.py` as a non-blocking background task inside `matrix_listener.py` whenever a new message arrives.
- [ ] Write unit tests in `test_extractor.py` covering multi-turn chat threads (e.g., Msg 1: "Dinner Friday?", Msg 2: "Keen", Msg 3: "7:30pm at Chaco Bar") and casual non-event messages.

### Verification Gate
- [ ] `cd backend && pytest tests/test_extractor.py -v` passes all multi-turn and false-positive test cases.

---

## Phase 4: Google Calendar Sync & Events REST API
**Goal:** Allow confirming, editing, or dismissing detected events and syncing confirmed events to the user's primary Google Calendar.

### Files to Create/Modify
- `backend/app/gcal_service.py`
- `backend/app/routers/events.py`
- `backend/tests/test_events_api.py`

### Tasks
- [ ] Implement `gcal_service.py` with OAuth2 token handling (`token.json` / `credentials.json`) and `create_calendar_event(event_data) -> str` returning the Google `calendarEventId`.
- [ ] Create `routers/events.py`:
  - `GET /api/events?status=PENDING_REVIEW|CONFIRMED`
  - `POST /api/events/{id}/confirm` (accepts optional overrides for `title`, `startTime`, `endTime`, `location`; calls `gcal_service`; sets `status = CONFIRMED` and saves `calendarEventId`).
  - `POST /api/events/{id}/dismiss` (sets `status = DISMISSED`).
- [ ] Write `test_events_api.py` mocking the Google Calendar client to verify state transitions and payload formatting.

### Verification Gate
- [ ] `cd backend && pytest tests/test_events_api.py -v` passes.

---

## Phase 5: Next.js Unified Inbox & Events Dashboard
**Goal:** Build the single-page multi-platform chat interface with inline event banners and the dedicated Events Review & Agenda page.

### Files to Create/Modify
- `frontend/src/lib/api.ts`
- `frontend/src/lib/ws.ts`
- `frontend/src/components/SidebarNav.tsx`
- `frontend/src/components/PlatformFilterPills.tsx`
- `frontend/src/components/ChatThread.tsx`
- `frontend/src/components/InlineEventBanner.tsx`
- `frontend/src/app/inbox/page.tsx`
- `frontend/src/app/events/page.tsx`

### Tasks
- [ ] Initialize Next.js App Router project with TypeScript and Tailwind CSS in `frontend/`.
- [ ] Create typed API helpers (`api.ts`) and a WebSocket hook (`ws.ts`) that updates local state on `NEW_MESSAGE` and `EVENT_DETECTED`.
- [ ] Build `/inbox`:
  - Left column: Platform filter pills + sorted room list with platform badges.
  - Center column: Message history, reply input bar, and `InlineEventBanner` rendered directly beneath messages that triggered a `DetectedEvent` with quick `[Add to Calendar]` and `[Dismiss]` actions.
  - Right drawer: Upcoming events specific to the active room.
- [ ] Build `/events`:
  - Top section: **Pending Review Queue** cards showing source chat quote, platform badge, extracted date/time/location, inline edit modal, and `[Approve & Sync]` / `[Dismiss]` buttons.
  - Bottom section: **Confirmed Upcoming Agenda** with a deep-link button that jumps back to the exact message in `/inbox`.

### Verification Gate
- [ ] `cd frontend && npm run type-check && npm run build` completes with zero errors.
