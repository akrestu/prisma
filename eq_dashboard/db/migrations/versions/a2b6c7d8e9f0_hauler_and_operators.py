"""Hauler ID and operators per hourly line; operator master.

Revision ID: a2b6c7d8e9f0
Revises: f1a5b6c7d8e9
Create Date: 2026-09-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2b6c7d8e9f0"
down_revision: str | Sequence[str] | None = "f1a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name, typ in (("loader_nrp", sa.String(30)), ("hauler", sa.String(40)), ("hauler_nrp", sa.String(30)),
                      ("hauler_operator", sa.String(120))):
        op.add_column("hourly_row", sa.Column(name, typ, nullable=True))
    op.create_table(
        "operators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site", sa.String(40), nullable=False, index=True),
        sa.Column("nrp", sa.String(30), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("position", sa.String(60)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("site", "nrp"),
    )


def downgrade() -> None:
    op.drop_table("operators")
    for name in ("hauler_operator", "hauler_nrp", "hauler", "loader_nrp"):
        op.drop_column("hourly_row", name)
