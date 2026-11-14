"""Data quality findings carry the figure they concern (amount + measure: L, BCM, t, h), so a dashboard total can be
reconciled with the source file. Findings of earlier uploads keep both empty until the month is uploaded again.

Revision ID: b6c0d1e2f3a4
Revises: a5b9c0d1e2f3
Create Date: 2026-11-14
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6c0d1e2f3a4"
down_revision: str | Sequence[str] | None = "a5b9c0d1e2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dq_findings", sa.Column("amount", sa.Float(), nullable=True))
    op.add_column("dq_findings", sa.Column("measure", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("dq_findings", "measure")
    op.drop_column("dq_findings", "amount")
