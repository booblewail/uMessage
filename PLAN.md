# uMessage v1 — Plan

The spec is [booblewail/uMessage#1](https://github.com/booblewail/uMessage/issues/1). Work is split into tracer-bullet tickets (its sub-issues); each ticket says what blocks it, and any ticket whose blockers are closed can be picked up. Domain language is in `CONTEXT.md`, decisions in `docs/adr/`.

## Tickets

| # | Ticket | Blocked by | Who |
|---|--------|-----------|-----|
| [#2](https://github.com/booblewail/uMessage/issues/2) | Phase 0: Beeper Desktop API spike on the Mac | — | Agent writes script, user runs it |
| [#3](https://github.com/booblewail/uMessage/issues/3) | Walking skeleton: one command, Beeper status, demo mode | — | Agent |
| [#4](https://github.com/booblewail/uMessage/issues/4) | Chats and Messages in the inbox (First Import) | #3 | Agent |
| [#5](https://github.com/booblewail/uMessage/issues/5) | New Messages appear live in the inbox | #4 | Agent |
| [#6](https://github.com/booblewail/uMessage/issues/6) | Reply from the inbox | #5 | Agent |
| [#7](https://github.com/booblewail/uMessage/issues/7) | Scroll back past stored history | #4 | Agent |
| [#8](https://github.com/booblewail/uMessage/issues/8) | Detected Event banner beneath its Anchor Message | #5 | Agent |
| [#9](https://github.com/booblewail/uMessage/issues/9) | Confirm a Detected Event into a Calendar Entry | #8 | Agent (user signs in to Google) |
| [#10](https://github.com/booblewail/uMessage/issues/10) | Review page, agenda, links to the Anchor Message | #9 | Agent |
| [#11](https://github.com/booblewail/uMessage/issues/11) | Excluded Chats | #8 | Agent |
| [#12](https://github.com/booblewail/uMessage/issues/12) | "Already on your calendar" hint | #9 | Agent |
| [#13](https://github.com/booblewail/uMessage/issues/13) | Real Beeper Desktop Message Source | #2, #6, #7 | Agent, user verifies on Mac |
| [#14](https://github.com/booblewail/uMessage/issues/14) | Live accuracy check of plan detection with Gemini | #8 | Agent writes, user runs |

## How tickets are implemented

1. Read `CONTEXT.md`, the relevant ADRs and the ticket.
2. Test-first at the agreed seam: the backend HTTP API + WebSocket with fake adapters (Message Source, Plan Model, Calendar) injected via the app factory. Real adapters get contract tests against recorded responses.
3. `make test` and `make lint` green; frontend changes also pass type-check, lint, build and a demo-mode browser smoke test.
4. Code review, commit referencing the ticket, close the ticket.
