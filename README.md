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

### Using it

- **Inbox** (`/inbox`): every Chat, newest first, with Platform filters. New Messages arrive live; reply from the box under a Chat; scroll up for older Messages (past what First Import kept, fetched from Beeper). "Plan detection on/off" makes a Chat an Excluded Chat. "Plans" opens a side panel with the open Chat's upcoming plans.
- **Plans spotted in a Chat** show beneath their Anchor Message: "Add to Calendar" lets you edit the title, time and place, then puts it on your calendar ("On your calendar"); or Dismiss it. If the Chat already has an upcoming Calendar Entry from uMessage, the plan says so ("You already have *Dinner at Mum's, Fri 19:00* from this Chat"), so a changed plan doesn't end up on your calendar twice by accident. uMessage never edits or deletes Calendar Entries.
- **Plans page** (`/events`, "Plans" in the header, with the number waiting for review): the Pending Review queue (Approve & Sync, or Dismiss) and an agenda of upcoming Confirmed plans by day. Both update live.
- **Links back**: every plan links to its Anchor Message, `/inbox?chat=<id>&message=<id>`, which opens the Chat scrolled to that Message, highlighted; scroll down for the newer Messages.

In demo mode scripted Messages arrive about every `DEMO_NEW_MESSAGE_SECONDS` and a Chat is checked for plans `PLAN_SETTLE_SECONDS` after it goes quiet; for a quick tour, try `UMESSAGE_MODE=demo DEMO_NEW_MESSAGE_SECONDS=8 PLAN_SETTLE_SECONDS=2 make dev` (Mum invites you to dinner first, then moves it to 7:30).

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

A plan's Calendar Entry has its title, time (a plan without an end time lasts `DEFAULT_PLAN_DURATION_MINUTES`, an hour by default), location, and a description quoting the Chat it came from. Demo mode uses a fake calendar instead and never touches Google. Each Calendar Entry gets an id derived from its plan (and a random id of your uMessage database), so if uMessage stops just as Google creates it, confirming the plan again finds that same Calendar Entry instead of adding a second one.

### Checking plan detection accuracy

Before trusting plan detection with your real Chats, check how well your Gemini model does on a set of made-up Chats with known answers (`backend/tests/fixtures/plan_eval/`: multi-Message plans, revisions of a pending plan, relative dates like "Friday" said on a Sunday or "tomorrow" said yesterday, all-day plans and trips, and things that are not plans: deadlines, other people's appointments, vague intentions, small talk with times, cancelled plans).

1. Put your paid-tier key in `.env` as `GEMINI_API_KEY=...` (and `GEMINI_MODEL` if you want a model other than the default).
2. Run:

   ```bash
   make eval-plans
   ```

   It asks Gemini about each Chat (about one API call per case), prints a PASS/FAIL table and the overall score, and writes the details, including the model's reason for each decision, to `backend/data/plan-eval-report.md`. A case passes when the decision is right (nothing / new / update of the right plan) and so are its start date and time, all-day flag and, where the case names one, end date and place. Plans less sure than `PLAN_CONFIDENCE_THRESHOLD` count as nothing, as in the app. The run fails if fewer than 80% of cases pass (`PLAN_EVAL_MIN_SCORE=0.9 make eval-plans` to change that).
3. Share `backend/data/plan-eval-report.md` (it contains only the made-up Chats, never your own).

Without a key the check is skipped; `make test` never calls Gemini.

## Development

```bash
make test    # backend tests: the HTTP API driven in-process with fake adapters
make lint    # ruff check + format check, frontend type-check, lint and build
```

`backend/` is FastAPI + SQLAlchemy (async, SQLite) + Alembic, managed with uv; `frontend/` is Next.js (App Router) with Tailwind CSS. `CLAUDE.md` has the architecture and conventions.
