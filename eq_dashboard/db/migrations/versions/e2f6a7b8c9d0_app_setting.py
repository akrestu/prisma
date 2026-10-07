"""Application settings (key → value), first used for the Hourly Production cutover date.

Revision ID: e2f6a7b8c9d0
Revises: d1e5f6a7b8c9
Create Date: 2026-10-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d1e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_setting",
        sa.Column("key", sa.String(60), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(60), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_setting")
