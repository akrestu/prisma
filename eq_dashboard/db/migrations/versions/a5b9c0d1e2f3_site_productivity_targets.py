"""One set of productivity targets per site: excavator models (hourly_model_target) and, new, hauler models
(site_hauler_target). The company-wide Production Data defaults are folded in and dropped: every site gets the
default of a model where it has no value of its own (an existing site value is never overwritten).

Revision ID: a5b9c0d1e2f3
Revises: f3a7b8c9d0e1
Create Date: 2026-10-08
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a5b9c0d1e2f3"
down_revision: str | Sequence[str] | None = "f3a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def norm(col: str) -> str:
    """Model key as core.prod_target.norm: upper case, no spaces, no leading CAT ('CAT 6020B' = '6020B')."""
    return f"regexp_replace(upper(replace({col}, ' ', '')), '^CAT', '')"


SITES = "SELECT code FROM sites WHERE active AND code <> 'UNMAPPED'"


def upgrade() -> None:
    op.create_table(
        "site_hauler_target",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site", sa.String(40), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("basis", sa.String(10), nullable=False),           # internal | client
        sa.Column("ob", sa.Float(), nullable=True),                  # BCM/h
        sa.Column("coal", sa.Float(), nullable=True),                # t/h
        sa.UniqueConstraint("site", "model", "basis"),
    )
    op.create_index("ix_site_hauler_target_site", "site_hauler_target", ["site"])
    # excavators: fill the empty values of a site's own row, then add the models the site has no row for
    op.execute(f"""
        UPDATE hourly_model_target h SET ob = COALESCE(h.ob, d.pdty_ob), mud = COALESCE(h.mud, d.pdty_mud),
               coal = COALESCE(h.coal, d.pdty_coal)
        FROM loader_model_target d WHERE h.basis = d.basis AND {norm('h.model')} = {norm('d.model')}
    """)
    op.execute(f"""
        INSERT INTO hourly_model_target (site, model, basis, ob, mud, coal)
        SELECT DISTINCT ON (s.code, d.basis, {norm('d.model')}) s.code, d.model, d.basis, d.pdty_ob, d.pdty_mud,
               d.pdty_coal
        FROM ({SITES}) s CROSS JOIN loader_model_target d
        WHERE NOT EXISTS (SELECT 1 FROM hourly_model_target h WHERE h.site = s.code AND h.basis = d.basis
                          AND {norm('h.model')} = {norm('d.model')})
        ORDER BY s.code, d.basis, {norm('d.model')}, d.model
    """)
    op.execute(f"""
        INSERT INTO site_hauler_target (site, model, basis, ob, coal)
        SELECT DISTINCT ON (s.code, d.basis, {norm('d.model')}) s.code, d.model, d.basis, d.pdty_ob, d.pdty_coal
        FROM ({SITES}) s CROSS JOIN hauler_model_target d
        ORDER BY s.code, d.basis, {norm('d.model')}, d.model
    """)
    op.drop_table("hauler_model_target")
    op.drop_table("loader_model_target")


def downgrade() -> None:
    op.create_table(
        "loader_model_target",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("basis", sa.String(10), nullable=False),
        sa.Column("pdty_ob", sa.Float(), nullable=True),
        sa.Column("pdty_mud", sa.Float(), nullable=True),
        sa.Column("pdty_coal", sa.Float(), nullable=True),
        sa.UniqueConstraint("model", "basis"),
    )
    op.create_table(
        "hauler_model_target",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("basis", sa.String(10), nullable=False),
        sa.Column("pdty_ob", sa.Float(), nullable=True),
        sa.Column("pdty_coal", sa.Float(), nullable=True),
        sa.UniqueConstraint("model", "basis"),
    )
    op.drop_index("ix_site_hauler_target_site", "site_hauler_target")
    op.drop_table("site_hauler_target")
