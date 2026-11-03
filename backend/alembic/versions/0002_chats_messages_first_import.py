"""Chats, Messages and the First Import record (#4).

Times are naive UTC (`app.models.UtcDateTime`); Platform and Chat kind are stored by value.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(), nullable=False),
        sa.Column("excluded", sa.Boolean(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chats")),
        sa.UniqueConstraint("source_id", name=op.f("uq_chats_source_id")),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("sender_name", sa.String(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("outbound", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_id"],
            ["chats.id"],
            name=op.f("fk_messages_chat_id_chats"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint("chat_id", "source_id", name="uq_messages_chat_id_source_id"),
    )
    op.create_index("ix_messages_chat_id_sent_at", "messages", ["chat_id", "sent_at"])
    op.create_table(
        "first_import",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.Column("chats_imported", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_first_import_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_first_import")),
    )


def downgrade() -> None:
    op.drop_table("first_import")
    op.drop_index("ix_messages_chat_id_sent_at", table_name="messages")
    op.drop_table("messages")
    op.drop_table("chats")
