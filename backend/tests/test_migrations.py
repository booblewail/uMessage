"""`models.py` is the schema's source of truth; the Alembic migrations must build exactly it."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.models import Base


def test_migrations_build_the_schema_the_models_describe(database_url: str) -> None:
    sync_url = make_url(database_url).set(drivername="sqlite")
    engine = create_engine(sync_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            differences = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert differences == []
