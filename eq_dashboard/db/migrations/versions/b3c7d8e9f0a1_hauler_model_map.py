"""Hauler model → load-factor model mapping per site.

Revision ID: b3c7d8e9f0a1
Revises: a2b6c7d8e9f0
Create Date: 2026-09-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3c7d8e9f0a1"
down_revision: str | Sequence[str] | None = "a2b6c7d8e9f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hauler_model_map",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site", sa.String(40), nullable=False, index=True),
        sa.Column("unit_model", sa.String(80), nullable=False),
        sa.Column("load_model", sa.String(80), nullable=False),
        sa.UniqueConstraint("site", "unit_model"),
    )


def downgrade() -> None:
    op.drop_table("hauler_model_map")
