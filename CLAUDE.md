# Unified Matrix Inbox & AI Calendar Sync

## Project Overview
A full-stack unified messaging client and automated event extractor.
- **Ingestion:** Connects to a Matrix Homeserver (Beeper or local Conduit) via `matrix-nio`.
- **Backend:** Python 3.12, FastAPI, Prisma Client Py, PostgreSQL, Google GenAI SDK (`gemini-2.5-flash`), Google Calendar API.
- **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS, Lucide Icons.

## Monorepo Structure
```text
.
├── docker-compose.yml          # PostgreSQL + Redis/Matrix local services
├── backend/
│   ├── pyproject.toml
│   ├── prisma/schema.prisma    # Single source of truth for DB schema
│   ├── app/
│   │   ├── main.py             # FastAPI entrypoint + WebSocket manager
│   │   ├── config.py           # Pydantic Settings (.env loader)
│   │   ├── matrix_listener.py  # Async matrix-nio sync loop + room/message ingest
│   │   ├── extractor.py        # Regex pre-filter + 5-msg context + Gemini structured JSON
│   │   ├── gcal_service.py     # Google Calendar OAuth2 & event insertion
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
