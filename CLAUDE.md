# uMessage: Unified Inbox & Plan Detection

## Project Overview
A personal, single-user companion to Beeper that runs on the user's Mac (ADR-0002): one inbox across iMessage, Instagram, Messenger, WhatsApp and Discord, which spots plans in Chats and, once the user approves, adds them to Google Calendar.
- **Ingestion:** Beeper Desktop's local API on `127.0.0.1` (ADR-0003, proposed until the Phase 0 spike confirms it; Matrix via `matrix-nio` is the fallback).
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async) + Alembic on SQLite (ADR-0001, ADR-0004), Google GenAI SDK (model from `GEMINI_MODEL`, ADR-0005), Google Calendar API.
- **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS, Lucide Icons.

Read `CONTEXT.md` for the domain language (Chat, Message, Detected Event, Calendar Entry, Anchor Message, ...) and use it in code, tests, issues and UI copy. Decisions live in `docs/adr/`. Work is tracked as GitHub issues (see Agent skills below); `PLAN.md` is the overview.

## Architecture
The backend core never talks to the outside world directly. Three adapter interfaces sit at the edges, each with a real and a fake implementation:
- **Message Source**: lists Chats, reads Messages, sends Messages (Beeper Desktop adapter; fake with fixture Chats).
- **Plan Model**: turns a window of Messages into a decision about a Detected Event (Gemini adapter; fake).
- **Calendar**: creates Calendar Entries (Google adapter; fake).

The app is built by an app factory that takes these three adapters, so tests and **demo mode** (`UMESSAGE_MODE=demo`: fake adapters, seeded fixture Chats, no credentials needed) run the real app with fakes.

## Repository Structure
```text
.
├── Makefile                    # make dev / test / lint / google-auth
├── .env.example                # every setting, documented
├── CONTEXT.md                  # Domain glossary
├── PLAN.md                     # Overview + links to the GitHub issues
├── docs/
│   ├── adr/                    # Architecture decision records
│   └── agents/                 # Agent-skill config: issue tracker, triage labels, domain docs
├── backend/                    # FastAPI, managed with uv
│   ├── alembic/versions/       # Migrations
│   ├── scripts/                # beeper_spike.py (Phase 0), google_auth.py (make google-auth)
│   ├── app/
│   │   ├── main.py             # App factory (create_app / build_app), lifespan, background tasks
│   │   ├── config.py, models.py, schemas.py   # Settings, SQLAlchemy models, API models (camelCase)
│   │   ├── first_import.py, live_updates.py, inbox.py, replies.py   # Chats and Messages
│   │   ├── plan_detection.py, plan_prefilter.py   # Detected Events from new Messages
│   │   ├── detected_events.py  # Listing/dismissing Detected Events; their API views (+ hint)
│   │   ├── calendar_entries.py # Confirm -> Calendar Entry, exactly once
│   │   ├── adapters/           # protocols.py; beeper_desktop, gemini, google_calendar; fakes, demo_fixtures
│   │   └── routers/            # status, health, chats (+ messages, reply), events, ws
│   └── tests/                  # Pytest: HTTP API + WebSocket with fake adapters; adapter contracts
└── frontend/src/               # Next.js (App Router), Tailwind, Lucide
    ├── app/                    # /inbox (?chat=&message=), /events (review queue + agenda)
    ├── components/             # UI components (<200 lines per file)
    └── lib/                    # api.ts (typed REST client), ws.ts (live socket), use* hooks
```

## Commands
```bash
make dev                                         # backend + frontend, opens the inbox
UMESSAGE_MODE=demo make dev                      # same, with fake adapters and fixture Chats
cd backend && uv sync                            # install backend deps
cd backend && uv run alembic upgrade head        # apply migrations
cd backend && uv run pytest                      # tests (no external services)
cd backend && uv run pytest -m live              # calls the real Gemini API (needs GEMINI_API_KEY)
cd backend && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run type-check && npm run lint && npm run build
```

## Conventions & Guardrails
- Tests drive the app through its HTTP API and WebSocket with fake adapters; don't test internals or mock internal collaborators.
- Schema changes go through the SQLAlchemy models plus a new Alembic migration; never edit an applied migration.
- All times are stored in UTC (SQLite has no time-zone type); convert to `USER_TIMEZONE` only for display and for resolving relative dates against each Message's own timestamp.
- DB columns are snake_case; API JSON is camelCase (Pydantic alias generator).
- Long-running background work uses tracked `asyncio` tasks, not FastAPI `BackgroundTasks`; run uvicorn with a single worker.
- Blocking SDKs (Google API client) are called via `asyncio.to_thread`.
- All `/api/*` routes (except health) and `/ws` require `API_TOKEN`; the API binds to `127.0.0.1` only.
- Excluded Chats are never sent to the Plan Model.
- Never commit `.env`, `token.json`, `credentials.json` or the SQLite database.
- Frontend components stay under 200 lines per file.

## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues on `booblewail/uMessage` (`gh` locally, GitHub MCP tools in cloud sessions). See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` plus `docs/adr/` at the repo root. See `docs/agents/domain.md`.
