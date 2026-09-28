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
ADMIN_PAGES = ["users_roles", "targets_plan", "pm_interval", "sites_mapping", "audit_log", "unit_population"]


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
    assert vals["PA (%)"] == "65.2%"
    assert vals["OB (BCM)"] == "778,796"
    assert vals["Coal (t)"] == "93,724.8"  # excludes tickets with an unknown loader (UNMAPPED 984.3 t)


def run_path(path, user):
    at = AppTest.from_file(str(APP_DIR / path), default_timeout=180)
    at.session_state["user"] = user
    at.run()
    return at


def test_data_explorer_scoped_to_user_sites(world):
    at = run_path("pages/data/explorer.py", load_user(world, "adm"))
    assert not at.exception, [e.value for e in at.exception]
    at = run_path("pages/data/explorer.py", load_user(world, "sm"))  # Site Manager BAU
    assert not at.exception
    assert at.multiselect(key="dx_site").options == ["WBK-BAU"]
    df = at.dataframe[0].value
    assert len(df) and set(df["site"]) == {"WBK-BAU"}


def test_delete_all_data_admin_only_and_keeps_settings(world):
    from sqlalchemy import func, select
    assert any("do not have access" in e.value for e in run("delete_data", load_user(world, "vw")).error)
    at = run("delete_data", load_user(world, "adm"))
    assert not at.exception
    at.text_input[0].input("delete all data")  # wrong case → refused
    at.button[0].click().run()
    assert any("exactly" in e.value for e in at.error)
    assert world.scalar(select(func.count()).select_from(m.FactEvent)) > 0
    n_targets = world.scalar(select(func.count()).select_from(m.Target))
    at.text_input[0].input("DELETE ALL DATA")
    at.button[0].click().run()
    assert not at.exception
    world.expire_all()
    for model in (m.Upload, m.UploadSite, m.FactEvent, m.FactRitase, m.DQFinding):
        assert world.scalar(select(func.count()).select_from(model)) == 0
    assert world.scalar(select(func.count()).select_from(m.Target)) == n_targets
    assert world.scalar(select(func.count()).select_from(m.User)) == 3


def test_data_prod_page_tabs_by_role(world):
    at = run_path("pages/data/upload.py", load_user(world, "adm"))
    assert not at.exception, [e.value for e in at.exception]
    assert [t.label for t in at.tabs] == ["Import", "Template", "Export"]
    at = run_path("pages/data/upload.py", load_user(world, "sm"))   # Site Manager: template + export only
    assert not at.exception
    assert any("Only Admins and Data Officers can import" in i.value for i in at.info)
    assert at.multiselect(key="exp_sites").options == ["WBK-BAU"]
    assert any("do not have access" in e.value for e in run_path("pages/data/upload.py", load_user(world, "vw")).error)


def test_page_summary_escapes_html(monkeypatch):
    from core import dash
    shown = []
    monkeypatch.setattr(dash.st, "markdown", lambda body, **k: shown.append(body))
    dash.summary("<img src=x onerror=alert(1)> causes 32% of down hours")
    assert "<img" not in shown[0] and "&lt;img" in shown[0]


def test_tv_version_key_changes_when_a_target_value_is_edited(world):
    from pages.tv.screen import version_key
    before = version_key("WBK-MAS")
    t = world.query(m.Target).filter(m.Target.site == "WBK-MAS").first()
    t.uoa = 0.61
    world.commit()
    assert version_key("WBK-MAS") != before


def test_week_and_shift_filters_apply_to_production_fuel_and_stoppages(world):
    from sqlalchemy import func, select
    adm = load_user(world, "adm")
    at = run("overview", adm)
    full = {mt.label: mt.value for mt in at.metric}
    at.sidebar.multiselect(key="f_week").select("Week 1").run()
    w1 = {mt.label: mt.value for mt in at.metric}
    assert not at.exception
    r = m.FactRitase
    ob_w1 = world.scalar(select(func.sum(r.volume)).where(r.material_group == "OB", func.extract("day", r.date) <= 7,
                                                           r.site != "UNMAPPED"))
    assert w1["OB (BCM)"] == f"{ob_w1:,.0f}" and w1["OB (BCM)"] != full["OB (BCM)"]
    assert w1["Fuel (L)"] != full["Fuel (L)"]
    assert w1["MTBS (hrs)"] != full["MTBS (hrs)"]
    at.sidebar.segmented_control(key="f_shift").set_value(["DS"]).run()   # stoppages follow the shift too
    assert {mt.label: mt.value for mt in at.metric}["MTTR (hrs)"] != w1["MTTR (hrs)"]


def test_filters_restore_from_url_and_save_as_default(world):
    at = AppTest.from_file(str(APP_DIR / "pages/dashboard/overview.py"), default_timeout=180)
    at.session_state["user"] = load_user(world, "adm")
    at.query_params["site"] = "WBK-BAU"
    at.query_params["period"] = "last7"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.sidebar.multiselect(key="f_site").value == ["WBK-BAU"]
    assert at.sidebar.selectbox(key="f_period").value == "last7"
    head = at.markdown[0].value
    assert "WBK-BAU" in head and "– 23 Sep 2026" in head and "last 7 days" in head
    at.sidebar.button(key="flt_save").click().run()
    world.expire_all()
    saved = world.query(m.User).filter(m.User.username == "adm").one().default_filters
    assert saved["f_site"] == ["WBK-BAU"] and saved["f_period"] == "last7"
    # a new session without URL parameters opens with the saved default
    at2 = run("overview", load_user(world, "adm"))
    assert at2.sidebar.multiselect(key="f_site").value == ["WBK-BAU"]


def test_system_health_for_admin_only(world):
    world.add(m.AuditLog(username="system", action="backup_ok", detail="eq_dashboard_2026-09-28.dump 12M"))
    world.commit()
    at = run_path("pages/home.py", load_user(world, "adm"))
    assert not at.exception, [e.value for e in at.exception]
    labels = {mt.label: mt for mt in at.metric}
    assert "Last backup" in labels and "12M" in labels["Last backup"].delta
    vw = run_path("pages/home.py", load_user(world, "vw"))
    assert "Last backup" not in {mt.label for mt in vw.metric}
