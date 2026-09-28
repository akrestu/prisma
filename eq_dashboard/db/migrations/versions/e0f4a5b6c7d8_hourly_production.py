"""Hourly production (flash): load factors, loader targets, shifts and rows; SR & distance targets.

Revision ID: e0f4a5b6c7d8
Revises: d9e3f4a5b6c7
Create Date: 2026-09-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e0f4a5b6c7d8"
down_revision: str | Sequence[str] | None = "d9e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("targets", sa.Column("sr", sa.Float(), nullable=True))
    op.add_column("targets", sa.Column("distance", sa.Float(), nullable=True))
    op.create_table(
        "load_factor",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site", sa.String(40), nullable=False, index=True),
        sa.Column("material", sa.String(80), nullable=False),
        sa.Column("material_group", sa.String(5), nullable=False),
        sa.Column("hauler_model", sa.String(80), nullable=False),
        sa.Column("muatan", sa.Float(), nullable=False),
        sa.UniqueConstraint("site", "material", "hauler_model"),
    )
    op.create_table(
        "loader_target",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site", sa.String(40), nullable=False, index=True),
        sa.Column("unit_id", sa.String(40), nullable=False),
        sa.Column("model", sa.String(80)),
        sa.Column("material_group", sa.String(5), nullable=False),
        sa.Column("target_per_hour", sa.Float(), nullable=False),
        sa.UniqueConstraint("site", "unit_id", "material_group"),
    )
    op.create_table(
        "hourly_shift",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site", sa.String(40), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("shift", sa.String(2), nullable=False),
        sa.Column("coordinator", sa.String(160), nullable=False, server_default=""),
        sa.Column("source", sa.String(10), nullable=False, server_default="web"),
        sa.Column("updated_by", sa.String(60)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("site", "date", "shift"),
    )
    op.create_table(
        "hourly_row",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("hourly_shift.id", ondelete="CASCADE"), nullable=False,
                  index=True),
        sa.Column("line", sa.Integer(), nullable=False),
        sa.Column("loader", sa.String(40), nullable=False),
        sa.Column("loader_model", sa.String(80)),
        sa.Column("operator", sa.String(120)),
        sa.Column("material", sa.String(80), nullable=False),
        sa.Column("material_group", sa.String(5), nullable=False),
        sa.Column("pit", sa.String(120)),
        sa.Column("disposal", sa.String(120)),
        sa.Column("distance_m", sa.Float()),
        sa.Column("hauler_model", sa.String(80), nullable=False),
        sa.Column("muatan", sa.Float(), nullable=False),
        sa.Column("target_per_hour", sa.Float()),
        sa.Column("remark_code", sa.String(10)),
        sa.Column("remark", sa.Text()),
        *[sa.Column(f"r{i}", sa.Float()) for i in range(1, 13)],
    )


def downgrade() -> None:
    op.drop_table("hourly_row")
    op.drop_table("hourly_shift")
    op.drop_table("loader_target")
    op.drop_table("load_factor")
    op.drop_column("targets", "distance")
    op.drop_column("targets", "sr")
