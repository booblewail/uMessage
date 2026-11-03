"""This database's random install id (idempotent Calendar Entry ids): a Detected Event's
Calendar Entry is keyed by it plus the Detected Event's id, so creating it again after a crash
finds the same entry, and two uMessage databases never pick the same one.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "installation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("install_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_installation_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_installation")),
    )


def downgrade() -> None:
    op.drop_table("installation")
