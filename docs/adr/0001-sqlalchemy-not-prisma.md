# SQLAlchemy 2.0 + Alembic instead of Prisma Client Python

The original design used Prisma Client Python with `schema.prisma` as the schema source of truth. We switched to SQLAlchemy 2.0 (async, `asyncpg`) with Alembic migrations, and `backend/app/models.py` is now the schema source of truth. Prisma Client Python is no longer maintained by its author, and it runs a separate Rust query engine plus a Node.js process alongside Python; building the whole data layer on a frozen project was not acceptable.

## Considered Options

- **Prisma Client Python**: familiar schema DSL, but unmaintained and heavy at runtime.
- **SQLModel**: thinner Pydantic-flavoured layer over SQLAlchemy; rejected to avoid an extra abstraction whose async story lags SQLAlchemy's own.
- **SQLAlchemy 2.0 + Alembic** (chosen): actively maintained, first-class async, mature migrations.
