# Unified Matrix Inbox & AI Calendar Sync

## Project Overview
A full-stack unified messaging client and automated event extractor.
- **Ingestion:** Connects to a Matrix homeserver (Beeper, or a local Conduit-family homeserver for testing) via `matrix-nio`. See `docs/matrix-spike.md` for the chosen connection/encryption approach.
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async, `asyncpg`) + Alembic, PostgreSQL 16, Google GenAI SDK (model from `GEMINI_MODEL`), Google Calendar API.
- **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS, Lucide Icons.

The implementation is tracked phase by phase in `PLAN.md`. Work on one phase at a time and follow its workflow instructions.

## Monorepo Structure
```text
.
├── docker-compose.yml          # PostgreSQL 16 + local Matrix homeserver (tests)
├── .env.example
├── PLAN.md                     # Phased implementation plan / progress state
├── docs/
│   ├── agents/                 # Agent-skill config: issue tracker, triage labels, domain docs
│   └── matrix-spike.md         # Phase 0 findings: Beeper access, E2EE, platform detection
├── backend/
│   ├── pyproject.toml          # Managed with uv
│   ├── alembic/                # Migrations (alembic/versions/)
│   ├── scripts/
│   │   ├── matrix_spike.py     # Phase 0 feasibility script
│   │   └── google_auth.py      # One-time local OAuth → token.json
│   ├── app/
│   │   ├── main.py             # FastAPI entrypoint, lifespan, auth, CORS, /ws
│   │   ├── config.py           # Pydantic Settings (.env loader)
│   │   ├── db.py               # Async engine + session dependency
│   │   ├── models.py           # SQLAlchemy models — single source of truth for DB schema
│   │   ├── ws_manager.py       # WebSocket ConnectionManager (NEW_MESSAGE, EVENT_DETECTED)
│   │   ├── platforms.py        # Bridge state → Platform enum
│   │   ├── matrix_listener.py  # Async matrix-nio sync loop + room/message ingest
│   │   ├── extractor.py        # Regex pre-filter + debounce + 5-msg context + Gemini structured JSON
│   │   ├── gcal_service.py     # Google Calendar credentials & event insertion
│   │   └── routers/
│   │       ├── rooms.py        # GET /api/rooms, GET /api/rooms/{id}/messages, POST /reply
│   │       └── events.py       # GET /api/events, POST /confirm, POST /dismiss
│   └── tests/                  # Pytest suite
└── frontend/
    ├── package.json
    └── src/
        ├── app/
        │   ├── inbox/page.tsx  # Unified multi-platform chat view + inline event chips
        │   └── events/page.tsx # Pending review queue + confirmed calendar agenda
        ├── components/         # Modular UI components (<200 lines per file)
        └── lib/
            ├── api.ts          # Typed REST client
            └── ws.ts           # Reconnecting WebSocket hook
```

## Commands
```bash
docker compose up -d db                          # start PostgreSQL
cd backend && uv sync                            # install backend deps
cd backend && uv run alembic upgrade head        # apply migrations
cd backend && uv run uvicorn app.main:app --port 8000   # run API (single worker only)
cd backend && uv run pytest                      # unit tests (no external services)
cd backend && uv run pytest -m integration       # needs local homeserver
cd backend && uv run pytest -m live              # calls the real Gemini API
cd backend && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run type-check && npm run lint && npm run build
```

## Conventions & Guardrails
- Schema changes go through `models.py` plus a new Alembic migration; never edit an applied migration.
- DB columns are snake_case; API JSON is camelCase (Pydantic alias generator).
- All datetimes are timezone-aware (`timestamptz`); relative dates are resolved in `USER_TIMEZONE` against the message's own timestamp.
- The Matrix sync loop runs exactly once per deployment: run uvicorn with one worker; no `--workers N`.
- Long-running background work uses tracked `asyncio` tasks, not FastAPI `BackgroundTasks`.
- Blocking SDKs (Google API client) are called via `asyncio.to_thread`.
- Unit tests mock Gemini, Google Calendar and Matrix; real-service tests are marked `integration` / `live`.
- All `/api/*` routes (except health) and `/ws` require `API_TOKEN`; bind the API to localhost.
- Never commit `.env`, `token.json`, `credentials.json` or the Matrix crypto store.
- Use a paid Gemini API tier (or Vertex AI) — chat content is private.
- Frontend components stay under 200 lines per file.

## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues on `booblewail/uMessage` (`gh` locally, GitHub MCP tools in cloud sessions). See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` plus `docs/adr/` at the repo root. See `docs/agents/domain.md`.
