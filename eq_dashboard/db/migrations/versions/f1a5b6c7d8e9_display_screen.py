"""Screen type per TV: equipment (monthly) or hourly production.

Revision ID: f1a5b6c7d8e9
Revises: e0f4a5b6c7d8
Create Date: 2026-09-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a5b6c7d8e9"
down_revision: str | Sequence[str] | None = "e0f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("display_devices", sa.Column("screen", sa.String(12), nullable=False, server_default="equipment"))


def downgrade() -> None:
    op.drop_column("display_devices", "screen")
