"""Excluded Chats (#11): mark Messages stored while their Chat was excluded, which are never
sent to the Plan Model, not even once the Chat is included again.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("excluded_from_plans", sa.Boolean(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("excluded_from_plans")
