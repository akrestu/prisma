"""Unit population as a versioned master (effective date).

Revision ID: d9e3f4a5b6c7
Revises: c8d2e3f4a5b6
Create Date: 2026-09-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9e3f4a5b6c7"
down_revision: str | Sequence[str] | None = "c8d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "population_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_population_versions_effective_from", "population_versions", ["effective_from"])
    op.create_table(
        "population_units",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("population_versions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("unit_id", sa.String(40), nullable=False),
        sa.Column("type", sa.String(60)),
        sa.Column("description", sa.String(120)),
        sa.Column("model", sa.String(80)),
        sa.Column("manufacturer", sa.String(80)),
        sa.Column("site", sa.String(40), nullable=False),
        sa.UniqueConstraint("version_id", "unit_id"),
    )
    op.create_index("ix_population_units_version_id", "population_units", ["version_id"])


def downgrade() -> None:
    op.drop_table("population_units")
    op.drop_table("population_versions")
