"""SQLAlchemy models: the single source of truth for the database schema.

Every change here needs a new Alembic migration in `alembic/versions/`.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.adapters.protocols import ChatKind, Platform

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UtcDateTime(TypeDecorator[datetime]):
    """A timezone-aware datetime stored as naive UTC (SQLite has no `timestamptz`, ADR-0004).

    Writing a naive datetime is a bug and raises; reads come back aware, in UTC.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(f"naive datetime {value!r}: every stored time must be aware")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


def _str_enum(enum: type[Platform] | type[ChatKind]) -> Enum:
    """Store a StrEnum by value in a plain VARCHAR column (no native enum type)."""
    return Enum(
        enum,
        native_enum=False,
        create_constraint=False,
        length=16,
        values_callable=lambda members: [member.value for member in members],
    )


class Chat(Base):
    """A Chat on one Platform. Discord server channels are never stored (they aren't Chats)."""

    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String, unique=True)
    platform: Mapped[Platform] = mapped_column(_str_enum(Platform))
    kind: Mapped[ChatKind] = mapped_column(_str_enum(ChatKind))
    title: Mapped[str] = mapped_column(String)
    last_activity_at: Mapped[datetime] = mapped_column(UtcDateTime)
    # An Excluded Chat (#11) is still shown, but never checked for plans.
    excluded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


class Message(Base):
    """A text Message in a Chat; `outbound` marks the user's own (an Outbound Message)."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "source_id", name="uq_messages_chat_id_source_id"),
        Index("ix_messages_chat_id_sent_at", "chat_id", "sent_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    source_id: Mapped[str] = mapped_column(String)
    sender_name: Mapped[str] = mapped_column(String)
    sent_at: Mapped[datetime] = mapped_column(UtcDateTime)
    text: Mapped[str] = mapped_column(Text)
    outbound: Mapped[bool] = mapped_column(Boolean)


class FirstImportRecord(Base):
    """The single row recording that First Import has completed, so it never runs again."""

    __tablename__ = "first_import"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    completed_at: Mapped[datetime] = mapped_column(UtcDateTime)
    chats_imported: Mapped[int] = mapped_column(Integer)
