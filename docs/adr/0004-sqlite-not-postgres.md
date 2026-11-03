# SQLite instead of PostgreSQL

uMessage is a single-user app on the user's laptop (ADR-0002), so we store data in one SQLite file instead of running PostgreSQL in Docker: nothing extra to install or keep running on the Mac, and backup is copying a file. SQLAlchemy and Alembic (ADR-0001) support it unchanged.

## Consequences

- SQLite has no time-zone-aware timestamp type: every time is stored in UTC and converted to the user's time zone only for display and for resolving relative dates.
- There is no row locking (`SELECT ... FOR UPDATE`): confirming a Detected Event is a single conditional update that only succeeds while it is still Pending Review, which also keeps a double-click from creating two Calendar Entries.
- Moving to PostgreSQL later (e.g. for multiple users) is a migration, not a rewrite.
