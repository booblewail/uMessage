"""Detected Events: plans found in Chats, beneath their Anchor Message (#8).

Times are naive UTC (`app.models.UtcDateTime`); the status is stored by value.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "detected_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("anchor_message_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=True),
        sa.Column("all_day", sa.Boolean(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("calendar_entry_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_id"],
            ["chats.id"],
            name=op.f("fk_detected_events_chat_id_chats"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["anchor_message_id"],
            ["messages.id"],
            name=op.f("fk_detected_events_anchor_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_detected_events")),
        sa.UniqueConstraint("calendar_entry_id", name=op.f("uq_detected_events_calendar_entry_id")),
    )
    op.create_index("ix_detected_events_chat_id_status", "detected_events", ["chat_id", "status"])
    op.create_index("ix_detected_events_start_at", "detected_events", ["start_at"])
    op.create_index(
        op.f("ix_detected_events_anchor_message_id"), "detected_events", ["anchor_message_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_detected_events_anchor_message_id"), table_name="detected_events")
    op.drop_index("ix_detected_events_start_at", table_name="detected_events")
    op.drop_index("ix_detected_events_chat_id_status", table_name="detected_events")
    op.drop_table("detected_events")
