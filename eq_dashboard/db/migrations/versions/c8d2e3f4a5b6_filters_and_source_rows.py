"""Saved sidebar filters per user; source Excel row number on fact rows.

Revision ID: c8d2e3f4a5b6
Revises: b7c1e2d3f4a5
Create Date: 2026-09-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "b7c1e2d3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FACTS = ["fact_event", "fact_ritase_jam", "fact_coal_tiket", "fact_fuel", "fact_fuel_receipt"]


def upgrade() -> None:
    op.add_column("users", sa.Column("default_filters", sa.JSON(), nullable=True))
    for t in FACTS:
        op.add_column(t, sa.Column("row_ref", sa.Integer(), nullable=True))


def downgrade() -> None:
    for t in FACTS:
        op.drop_column(t, "row_ref")
    op.drop_column("users", "default_filters")
