"""TV devices: the link token also stored encrypted (app secret), so the link can be copied again later.

Revision ID: b9c3d4e5f6a7
Revises: a8b2c3d4e5f6
Create Date: 2026-10-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a8b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("display_devices", sa.Column("token_enc", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("display_devices", "token_enc")
