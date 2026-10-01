"""Separate targets: Production Data default productivity (loader + hauler per model) and Hourly Production
targets (per site × model, unit overrides per basis).

- loader_model_target (filled from Prod_Target) becomes the Production Data default for excavators; + pdty_coal.
- hauler_model_target: new, Production Data default for haulers.
- hourly_model_target: new, Hourly Production target per site × excavator model × basis.
- loader_target (unit overrides): + basis; existing overrides take the site's current target basis.
- hourly_row: + target_source (unit | hourly | default) so screens can mark default targets.

Revision ID: f7a1b2c3d4e5
Revises: e6f0a1b2c3d4
Create Date: 2026-10-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "e6f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("loader_model_target", sa.Column("pdty_coal", sa.Float(), nullable=True))
    op.create_table(
        "hauler_model_target",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("basis", sa.String(10), nullable=False),
        sa.Column("pdty_ob", sa.Float(), nullable=True),
        sa.Column("pdty_coal", sa.Float(), nullable=True),
        sa.UniqueConstraint("model", "basis"),
    )
    op.create_table(
        "hourly_model_target",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site", sa.String(40), nullable=False, index=True),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("basis", sa.String(10), nullable=False),
        sa.Column("ob", sa.Float(), nullable=True),
        sa.Column("mud", sa.Float(), nullable=True),
        sa.Column("coal", sa.Float(), nullable=True),
        sa.UniqueConstraint("site", "model", "basis"),
    )
    op.add_column("loader_target", sa.Column("basis", sa.String(10), nullable=False, server_default="internal"))
    op.execute("UPDATE loader_target t SET basis = COALESCE(s.target_basis, 'internal') "
               "FROM sites s WHERE s.code = t.site")
    op.drop_constraint("loader_target_site_unit_id_material_group_key", "loader_target", type_="unique")
    op.create_unique_constraint("loader_target_site_unit_id_material_group_basis_key", "loader_target",
                                ["site", "unit_id", "material_group", "basis"])
    op.add_column("hourly_row", sa.Column("target_source", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("hourly_row", "target_source")
    op.drop_constraint("loader_target_site_unit_id_material_group_basis_key", "loader_target", type_="unique")
    op.execute("DELETE FROM loader_target t USING sites s WHERE s.code = t.site "
               "AND t.basis <> COALESCE(s.target_basis, 'internal')")
    op.create_unique_constraint("loader_target_site_unit_id_material_group_key", "loader_target",
                                ["site", "unit_id", "material_group"])
    op.drop_column("loader_target", "basis")
    op.drop_table("hourly_model_target")
    op.drop_table("hauler_model_target")
    op.drop_column("loader_model_target", "pdty_coal")
