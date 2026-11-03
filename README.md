# uMessage

A personal companion to Beeper that runs on your Mac: one inbox across iMessage, Instagram, Messenger, WhatsApp and Discord, which spots plans in your Chats and, once you approve them, puts them on your Google Calendar. See `CONTEXT.md` for the vocabulary and `docs/adr/` for the decisions behind it.

## Running it

You need [uv](https://docs.astral.sh/uv/), Node.js 20.9+ and `make`.

### Demo mode first (no credentials needed)

```bash
UMESSAGE_MODE=demo make dev
```

This installs dependencies, creates `.env` from `.env.example` (with a fresh `API_TOKEN`), applies the database migrations, starts the backend on `http://127.0.0.1:8000` and the frontend on `http://127.0.0.1:3000`, and opens the inbox. Demo mode runs the real app on fake adapters (Message Source, Plan Model, Calendar), so nothing touches Beeper, Gemini or Google. Ctrl-C stops both servers.

On its first start uMessage runs First Import: the last 50 or so Messages of each Chat active in the past 30 days (Discord server channels are left out). In demo mode that brings in fixture Chats on all five Platforms; the progress shows in the inbox and in `GET /api/status`, and it never runs again once it has completed. To start over, delete the database (`backend/data/umessage.db`).

To see the inbox's "Beeper Desktop isn't running" state in demo mode:

```bash
UMESSAGE_MODE=demo DEMO_BEEPER_RUNNING=false make dev
```

### With Beeper Desktop

Open Beeper Desktop with its local API enabled, then run:

```bash
make dev
```

The inbox shows whether Beeper Desktop is running. Settings live in `.env`; every one is documented in `.env.example`.

### Connecting your real Beeper

1. In Beeper Desktop, open Settings → Developers, enable the local API and create an access token.
2. Put it in `.env` as `BEEPER_ACCESS_TOKEN=...`. `BEEPER_API_URL` defaults to Beeper Desktop's local address, `http://127.0.0.1:23373`.
3. Run `make dev` (real mode). First Import then brings in your Chats on iMessage, Instagram, Messenger, WhatsApp and Discord active in the past 30 days (Chats on other networks, and Discord server channels, are left out), and new Messages are picked up by polling Beeper Desktop every `NEW_MESSAGES_POLL_SECONDS`.

If the token is missing or wrong, the inbox shows Beeper Desktop as not running and the backend log says to set `BEEPER_ACCESS_TOKEN`. The adapter (`backend/app/adapters/beeper_desktop.py`) is built from the shapes in Beeper's official SDK and has not yet been checked against a real Beeper Desktop: the Phase 0 spike (`backend/scripts/beeper_spike.py`, #2) records real responses to confirm or adjust its mappings.

## Development

```bash
make test    # backend tests: the HTTP API driven in-process with fake adapters
make lint    # ruff check + format check, frontend type-check, lint and build
```

`backend/` is FastAPI + SQLAlchemy (async, SQLite) + Alembic, managed with uv; `frontend/` is Next.js (App Router) with Tailwind CSS. `CLAUDE.md` has the architecture and conventions.
