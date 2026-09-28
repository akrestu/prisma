"""Hourly TV screen: live or a fixed report date and shift per TV.

Revision ID: d5e9f0a1b2c3
Revises: c4d8e9f0a1b2
Create Date: 2026-09-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e9f0a1b2c3"
down_revision: str | Sequence[str] | None = "c4d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("display_devices", sa.Column("hourly_date", sa.Date(), nullable=True))
    op.add_column("display_devices", sa.Column("hourly_shift", sa.String(2), nullable=True))


def downgrade() -> None:
    op.drop_column("display_devices", "hourly_shift")
    op.drop_column("display_devices", "hourly_date")
