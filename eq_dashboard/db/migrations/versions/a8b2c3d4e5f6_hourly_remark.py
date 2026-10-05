"""Hourly Production: remarks per hour (hour, loader, optional hauler, code, text) instead of one per line.

Revision ID: a8b2c3d4e5f6
Revises: f7a1b2c3d4e5
Create Date: 2026-10-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f7a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hourly_remark",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("hourly_shift.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("loader", sa.String(40), nullable=False),
        sa.Column("hauler", sa.String(40), nullable=True),
        sa.Column("code", sa.String(10), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
    )
    op.create_index("ix_hourly_remark_shift_id", "hourly_remark", ["shift_id"])


def downgrade() -> None:
    op.drop_index("ix_hourly_remark_shift_id", table_name="hourly_remark")
    op.drop_table("hourly_remark")
