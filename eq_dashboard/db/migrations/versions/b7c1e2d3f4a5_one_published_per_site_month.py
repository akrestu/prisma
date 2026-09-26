"""At most one PUBLISHED version per site and month (partial unique index).

Revision ID: b7c1e2d3f4a5
Revises: 10451efbedde
Create Date: 2026-09-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c1e2d3f4a5"
down_revision: str | Sequence[str] | None = "10451efbedde"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("uq_upload_sites_published", "upload_sites", ["site_code", "month"], unique=True,
                    postgresql_where=sa.text("status = 'PUBLISHED'"))


def downgrade() -> None:
    op.drop_index("uq_upload_sites_published", table_name="upload_sites")
