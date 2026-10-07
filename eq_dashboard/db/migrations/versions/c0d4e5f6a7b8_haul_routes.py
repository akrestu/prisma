"""Hourly Production: destinations (Tujuan) and routes per loader + destination; vertical distance on shift lines.

Revision ID: c0d4e5f6a7b8
Revises: b9c3d4e5f6a7
Create Date: 2026-10-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c0d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b9c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "haul_destination",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site", sa.String(40), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("material_group", sa.String(5), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("site", "name"),
    )
    op.create_index("ix_haul_destination_site", "haul_destination", ["site"])
    op.create_table(
        "haul_route",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site", sa.String(40), nullable=False),
        sa.Column("loader", sa.String(40), nullable=False),
        sa.Column("destination", sa.String(120), nullable=False),
        sa.Column("pit", sa.String(120), nullable=True),
        sa.Column("dist_h", sa.Float(), nullable=True),
        sa.Column("dist_v", sa.Float(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.UniqueConstraint("site", "loader", "destination", "valid_from"),
    )
    op.create_index("ix_haul_route_site", "haul_route", ["site"])
    op.add_column("hourly_row", sa.Column("dist_v", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("hourly_row", "dist_v")
    op.drop_index("ix_haul_route_site", "haul_route")
    op.drop_table("haul_route")
    op.drop_index("ix_haul_destination_site", "haul_destination")
    op.drop_table("haul_destination")
