"""Hourly Production: one PIT and disposal master per site and material (haul_location) replaces the destinations
and the routes. Disposals are copied over; the PITs named in the routes become PIT rows of the destination's material.
The routes (pit and distances per loader + destination) are dropped: PIT, disposal and distances are typed per line.

Revision ID: f3a7b8c9d0e1
Revises: e2f6a7b8c9d0
Create Date: 2026-10-08
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "e2f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "haul_location",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),            # PIT | DISPOSAL
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("material_group", sa.String(5), nullable=False),   # OB | CG
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("site", "kind", "material_group", "name"),
    )
    op.create_index("ix_haul_location_site", "haul_location", ["site"])
    op.execute("""
        INSERT INTO haul_location (site, kind, name, material_group, active)
        SELECT site, 'DISPOSAL', name, material_group, active FROM haul_destination
    """)
    op.execute("""
        INSERT INTO haul_location (site, kind, name, material_group, active)
        SELECT DISTINCT r.site, 'PIT', TRIM(r.pit), d.material_group, TRUE
        FROM haul_route r JOIN haul_destination d ON d.site = r.site AND d.name = r.destination
        WHERE r.pit IS NOT NULL AND TRIM(r.pit) <> ''
    """)
    op.drop_index("ix_haul_route_site", "haul_route")
    op.drop_table("haul_route")
    op.drop_index("ix_haul_destination_site", "haul_destination")
    op.drop_table("haul_destination")


def downgrade() -> None:
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
    op.execute("""
        INSERT INTO haul_destination (site, name, material_group, active)
        SELECT DISTINCT ON (site, name) site, name, material_group, active FROM haul_location
        WHERE kind = 'DISPOSAL' ORDER BY site, name, material_group
    """)
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
    op.drop_index("ix_haul_location_site", "haul_location")
    op.drop_table("haul_location")
