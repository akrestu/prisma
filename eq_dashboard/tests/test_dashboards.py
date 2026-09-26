"""Setiap halaman dashboard & admin berjalan tanpa error dengan data asli, dan hak akses dihormati."""
from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from auth import security
from auth.access import ADMIN, SITE_MANAGER, VIEWER, load_user
from core import ingest as ing
from core.targets import import_targets
from db import models as m

from .conftest import APP_DIR, TARGET

DASHBOARDS = ["overview", "pa_ua", "time_distribution", "reliability", "production_ob", "coal_getting",
              "loader_fleet", "fuel", "data_quality"]
ADMIN_PAGES = ["users_roles", "targets_plan", "pm_interval", "sites_mapping", "audit_log"]


@pytest.fixture()
def world(db_session, sample_bytes, monkeypatch):
    from core.config import database_url
    s = db_session
    ing.ingest(s, sample_bytes, "Eq.Event.xlsb", username="t")
    if TARGET.exists():
        import_targets(s, TARGET.read_bytes())
    for us in s.query(m.UploadSite).filter(m.UploadSite.site_code != "UNMAPPED"):
        ing.publish(s, us, None, "t")
    security.create_user(s, "adm", "Adm", ADMIN, "Tambang-2026x", all_sites=True)
    security.create_user(s, "sm", "SM", SITE_MANAGER, "Tambang-2026x", sites=["WBK-BAU"])
    security.create_user(s, "vw", "VW", VIEWER, "Tambang-2026x", all_sites=True)
    s.commit()
    monkeypatch.setenv("DATABASE_URL", database_url(test=True))
    return s


def run(page, user):
    folder = "dashboard" if page in DASHBOARDS else "admin"
    at = AppTest.from_file(str(APP_DIR / f"pages/{folder}/{page}.py"), default_timeout=180)
    at.session_state["user"] = user
    at.run()
    return at


@pytest.mark.parametrize("page", DASHBOARDS + ADMIN_PAGES)
def test_page_runs_for_admin(world, page):
    at = run(page, load_user(world, "adm"))
    assert not at.exception, [e.value for e in at.exception]
    assert not any("do not have access" in e.value for e in at.error)


def test_viewer_sees_dashboards_not_admin(world):
    vw = load_user(world, "vw")
    assert not run("overview", vw).exception
    for page in ADMIN_PAGES:
        assert any("do not have access" in e.value for e in run(page, vw).error)


def test_site_manager_scope_on_dashboard_and_targets(world):
    sm = load_user(world, "sm")
    at = run("overview", sm)
    assert not at.exception
    assert at.sidebar.multiselect(key="f_site").options == ["WBK-BAU"]
    at = run("targets_plan", sm)
    assert not at.exception
    assert at.selectbox(key="tgt_site").options == ["WBK-BAU"]
    assert any("do not have access" in e.value for e in run("users_roles", sm).error)


def test_overview_numbers_weighted_across_sites(world):
    at = run("overview", load_user(world, "adm"))
    vals = {mt.label: mt.value for mt in at.metric}
    # MAS (T 63.252 jam, PA 71,07%) + BAU (T 35.028 jam, PA 54,49%) berbobot jam = 65,16%
    assert vals["PA"] == "65.2%"
    assert vals["OB (BCM)"] == "778,796"
    assert vals["Coal (t)"] == "93,724.8"  # excludes tickets with an unknown loader (UNMAPPED 984.3 t)
