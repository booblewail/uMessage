# uMessage v1 — Plan

The spec is [booblewail/uMessage#1](https://github.com/booblewail/uMessage/issues/1). Work is split into tracer-bullet tickets (its sub-issues); each ticket says what blocks it, and any ticket whose blockers are closed can be picked up. Domain language is in `CONTEXT.md`, decisions in `docs/adr/`.

## Status

The MVP is built: every agent ticket is done and the whole flow works end to end in demo mode (inbox across five Platforms, live Messages, replies, scroll-back, plan detection, confirm into Google Calendar, review page, hint, Excluded Chats). What's left needs the user's Mac and accounts.

## Tickets

| # | Ticket | Blocked by | Status |
|---|--------|-----------|--------|
| [#2](https://github.com/booblewail/uMessage/issues/2) | Phase 0: Beeper Desktop API spike on the Mac | — | **Open — user runs `backend/scripts/beeper_spike.py`** |
| [#3](https://github.com/booblewail/uMessage/issues/3) | Walking skeleton: one command, Beeper status, demo mode | — | Done |
| [#4](https://github.com/booblewail/uMessage/issues/4) | Chats and Messages in the inbox (First Import) | #3 | Done |
| [#5](https://github.com/booblewail/uMessage/issues/5) | New Messages appear live in the inbox | #4 | Done |
| [#6](https://github.com/booblewail/uMessage/issues/6) | Reply from the inbox | #5 | Done |
| [#7](https://github.com/booblewail/uMessage/issues/7) | Scroll back past stored history | #4 | Done |
| [#8](https://github.com/booblewail/uMessage/issues/8) | Detected Event banner beneath its Anchor Message | #5 | Done |
| [#9](https://github.com/booblewail/uMessage/issues/9) | Confirm a Detected Event into a Calendar Entry | #8 | Done (user runs `make google-auth` once) |
| [#10](https://github.com/booblewail/uMessage/issues/10) | Review page, agenda, links to the Anchor Message | #9 | Done |
| [#11](https://github.com/booblewail/uMessage/issues/11) | Excluded Chats | #8 | Done |
| [#12](https://github.com/booblewail/uMessage/issues/12) | "Already on your calendar" hint | #9 | Done |
| [#13](https://github.com/booblewail/uMessage/issues/13) | Real Beeper Desktop Message Source | #2, #6, #7 | **Built from Beeper's SDK; open until checked against a real Beeper Desktop** |
| [#14](https://github.com/booblewail/uMessage/issues/14) | Live accuracy check of plan detection with Gemini | #8 | **Open — needs the user's `GEMINI_API_KEY`** |

## How tickets are implemented

1. Read `CONTEXT.md`, the relevant ADRs and the ticket.
2. Test-first at the agreed seam: the backend HTTP API + WebSocket with fake adapters (Message Source, Plan Model, Calendar) injected via the app factory. Real adapters get contract tests against recorded responses.
3. `make test` and `make lint` green; frontend changes also pass type-check, lint, build and a demo-mode browser smoke test.
4. Code review, commit referencing the ticket, close the ticket.
