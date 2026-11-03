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

### Connecting Google Calendar

"Add to Calendar" on a plan uMessage spotted puts it on your primary Google Calendar. uMessage talks to Google with an OAuth client of your own, created once in Google Cloud (free):

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project (or pick one), then enable the **Google Calendar API** under *APIs & Services → Library*.
2. Under *APIs & Services → OAuth consent screen* (*Google Auth Platform*), set up the consent screen: user type **External**, publishing status **Testing**, and add your own Google account under **Test users**. It only ever needs to work for you.
3. Under *Credentials* (*Clients*), create an **OAuth client ID** of type **Desktop app**, and download its JSON to `backend/data/google-credentials.json` (or point `GOOGLE_CREDENTIALS_PATH` at it).
4. Run:

   ```bash
   make google-auth
   ```

   Your browser opens Google's sign-in; allow uMessage to "view and edit events on all your calendars" (the `calendar.events` scope: it can't see or change your calendar settings or sharing). The sign-in is saved to `backend/data/google-token.json` (`GOOGLE_TOKEN_PATH`); uMessage refreshes it as needed, and a running app picks it up without a restart.

Until you've signed in, everything else works and `GET /api/status` reports `calendar.connected: false`; "Add to Calendar" says to run `make google-auth`. With the consent screen in Testing mode Google expires the sign-in after 7 days, so run `make google-auth` again when uMessage says so (or publish the app to *In production*, unverified, which is fine for your own account). Both JSON files are secrets: they're git-ignored, never commit them.

A plan's Calendar Entry has its title, time (a plan without an end time lasts `DEFAULT_PLAN_DURATION_MINUTES`, an hour by default), location, and a description quoting the Chat it came from. Demo mode uses a fake calendar instead and never touches Google.

## Development

```bash
make test    # backend tests: the HTTP API driven in-process with fake adapters
make lint    # ruff check + format check, frontend type-check, lint and build
```

`backend/` is FastAPI + SQLAlchemy (async, SQLite) + Alembic, managed with uv; `frontend/` is Next.js (App Router) with Tailwind CSS. `CLAUDE.md` has the architecture and conventions.
