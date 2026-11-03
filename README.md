# uMessage

A personal companion to Beeper that runs on your Mac: one inbox across iMessage, Instagram, Messenger, WhatsApp and Discord, which spots plans in your Chats and, once you approve them, puts them on your Google Calendar. See `CONTEXT.md` for the vocabulary and `docs/adr/` for the decisions behind it.

## Running it

You need [uv](https://docs.astral.sh/uv/), Node.js 20.9+ and `make`.

### Demo mode first (no credentials needed)

```bash
UMESSAGE_MODE=demo make dev
```

This installs dependencies, creates `.env` from `.env.example` (with a fresh `API_TOKEN`), applies the database migrations, starts the backend on `http://127.0.0.1:8000` and the frontend on `http://127.0.0.1:3000`, and opens the inbox. Demo mode runs the real app on fake adapters (Message Source, Plan Model, Calendar), so nothing touches Beeper, Gemini or Google. Ctrl-C stops both servers.

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

## Development

```bash
make test    # backend tests: the HTTP API driven in-process with fake adapters
make lint    # ruff check + format check, frontend type-check, lint and build
```

`backend/` is FastAPI + SQLAlchemy (async, SQLite) + Alembic, managed with uv; `frontend/` is Next.js (App Router) with Tailwind CSS. `CLAUDE.md` has the architecture and conventions.
