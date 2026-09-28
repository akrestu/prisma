"""Prod_Target: excavator model targets (internal/client), hauler factors, target basis per site.

Revision ID: c4d8e9f0a1b2
Revises: b3c7d8e9f0a1
Create Date: 2026-09-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d8e9f0a1b2"
down_revision: str | Sequence[str] | None = "b3c7d8e9f0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sites", sa.Column("target_basis", sa.String(10), nullable=False, server_default="internal"))
    op.create_table(
        "loader_model_target",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("basis", sa.String(10), nullable=False),
        sa.Column("pdty_ob", sa.Float()),
        sa.Column("pdty_mud", sa.Float()),
        sa.UniqueConstraint("model", "basis"),
    )
    op.create_table(
        "hauler_factor",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family", sa.String(80), nullable=False, unique=True),
        *[sa.Column(c, sa.Float()) for c in ("tf_ob", "tf_mudb", "tf_mud", "tf_coal", "sp_empty", "sp_loaded",
                                             "sp_avg")],
    )


def downgrade() -> None:
    op.drop_table("hauler_factor")
    op.drop_table("loader_model_target")
    op.drop_column("sites", "target_basis")
