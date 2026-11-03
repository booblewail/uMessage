"""Scrolling back past stored history (#7): where the Message Source pages from, and whether
a Chat's history is complete.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chats", sa.Column("history_complete", sa.Boolean(), server_default="0", nullable=False)
    )
    op.add_column("messages", sa.Column("paging_key", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("paging_key")
    with op.batch_alter_table("chats") as batch:
        batch.drop_column("history_complete")
