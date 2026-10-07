"""Hourly Production: approval per shift (status, submitter, reviewer) and change requests for locked shifts.

Revision ID: d1e5f6a7b8c9
Revises: c0d4e5f6a7b8
Create Date: 2026-10-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c0d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hourly_shift", sa.Column("status", sa.String(10), nullable=False, server_default="DRAFT"))
    op.create_index("ix_hourly_shift_status", "hourly_shift", ["status"])
    op.add_column("hourly_shift", sa.Column("submitted_by", sa.String(60), nullable=True))
    op.add_column("hourly_shift", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("hourly_shift", sa.Column("reviewed_by", sa.String(60), nullable=True))
    op.add_column("hourly_shift", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("hourly_shift", sa.Column("review_note", sa.Text(), nullable=True))
    op.create_table(
        "hourly_change_request",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("hourly_shift.id", ondelete="CASCADE"), nullable=False),
        sa.Column("coordinator", sa.String(160), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("requested_by", sa.String(60), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_by", sa.String(60), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
    )
    op.create_index("ix_hourly_change_request_shift_id", "hourly_change_request", ["shift_id"])
    op.create_index("ix_hourly_change_request_status", "hourly_change_request", ["status"])


def downgrade() -> None:
    op.drop_index("ix_hourly_change_request_status", "hourly_change_request")
    op.drop_index("ix_hourly_change_request_shift_id", "hourly_change_request")
    op.drop_table("hourly_change_request")
    for c in ("review_note", "reviewed_at", "reviewed_by", "submitted_at", "submitted_by"):
        op.drop_column("hourly_shift", c)
    op.drop_index("ix_hourly_shift_status", "hourly_shift")
    op.drop_column("hourly_shift", "status")
