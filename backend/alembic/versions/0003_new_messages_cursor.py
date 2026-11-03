"""The cursor fetching new Messages resumes from (#5).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "new_messages_cursor",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cursor", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_new_messages_cursor_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_new_messages_cursor")),
    )


def downgrade() -> None:
    op.drop_table("new_messages_cursor")
