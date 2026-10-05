"""Setiap halaman dashboard & admin berjalan tanpa error dengan data asli, dan hak akses dihormati."""
from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from auth import security
from auth.access import ADMIN, SITE_MANAGER, VIEWER, load_user
from core import ingest as ing
from core.targets import import_targets
from db import models as m
from db import repo

from .conftest import APP_DIR, TARGET

DASHBOARDS = ["overview", "hourly", "pa_ua", "time_distribution", "reliability", "production_ob", "coal_getting",
              "loader_fleet", "fuel", "data_quality"]
ADMIN_PAGES = ["users_roles", "targets_plan", "pm_interval", "sites_mapping", "audit_log", "unit_population", "operators"]


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


@pytest.mark.parametrize("page", DASHBOARDS + ADMIN_PAGES)
def test_page_runs_on_fresh_install(db_session, monkeypatch, page):
    """A new server has no data yet: every page must still open (pm_interval used to crash on empty frames)."""
    from core.config import database_url
    security.create_user(db_session, "adm", "Adm", ADMIN, "Tambang-2026x", all_sites=True)
    db_session.commit()
    monkeypatch.setenv("DATABASE_URL", database_url(test=True))
    at = run(page, load_user(db_session, "adm"))
    assert not at.exception, [e.value for e in at.exception]


def test_viewer_sees_dashboards_not_admin(world):
    vw = load_user(world, "vw")
    assert not run("overview", vw).exception
    for page in ADMIN_PAGES:
        assert any("do not have access" in e.value for e in run(page, vw).error)


def test_site_manager_scope_on_dashboard_and_targets(world):
    sm = load_user(world, "sm")
    at = run("overview", sm)
    assert not at.exception
    assert at.multiselect(key="f_site").options == ["WBK-BAU"]
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


def test_delete_data_admin_only_per_dataset_and_keeps_settings(world):
    from sqlalchemy import func, select

    from core.validate import PRODUCTION_DATA
    assert any("do not have access" in e.value for e in run("delete_data", load_user(world, "vw")).error)
    at = run("delete_data", load_user(world, "adm"))
    assert not at.exception
    assert any("Pick the dataset" in i.value for i in at.info)            # nothing chosen → nothing to delete
    at.session_state["del_sets"] = [PRODUCTION_DATA]
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    at.text_input[0].input("delete")  # wrong case → refused
    at.button[0].click().run()
    assert any("exactly" in e.value for e in at.error)
    assert world.scalar(select(func.count()).select_from(m.FactEvent)) > 0
    n_targets = world.scalar(select(func.count()).select_from(m.Target))
    at.text_input[0].input("DELETE")
    at.button[0].click().run()
    assert not at.exception
    world.expire_all()
    for model in (m.Upload, m.UploadSite, m.FactEvent, m.FactRitase, m.DQFinding):
        assert world.scalar(select(func.count()).select_from(model)) == 0
    assert world.scalar(select(func.count()).select_from(m.Target)) == n_targets
    assert world.scalar(select(func.count()).select_from(m.User)) == 3
    assert world.scalar(select(func.count()).select_from(m.AuditLog).where(m.AuditLog.action == "delete_data")) == 1


def test_data_prod_page_tabs_by_role(world):
    at = run_path("pages/data/upload.py", load_user(world, "adm"))
    assert not at.exception, [e.value for e in at.exception]
    assert [t.label for t in at.tabs] == ["Import", "Edit", "Template", "Export"]
    at = run_path("pages/data/upload.py", load_user(world, "sm"))   # Site Manager: template + export only
    assert not at.exception
    assert any("Only Admins and Data Officers can import" in i.value for i in at.info)
    assert any("Only Admins and Data Officers can edit" in i.value for i in at.info)
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
    at.multiselect(key="f_week").select("Week 1").run()
    w1 = {mt.label: mt.value for mt in at.metric}
    assert not at.exception
    r = m.FactRitase
    ob_w1 = world.scalar(select(func.sum(r.volume)).where(r.material_group == "OB", func.extract("day", r.date) <= 7,
                                                           r.site != "UNMAPPED"))
    assert w1["OB (BCM)"] == f"{ob_w1:,.0f}" and w1["OB (BCM)"] != full["OB (BCM)"]
    assert w1["Fuel (L)"] != full["Fuel (L)"]
    assert w1["MTBS (hrs)"] != full["MTBS (hrs)"]
    at.segmented_control(key="f_shift").set_value(["DS"]).run()   # stoppages follow the shift too
    assert {mt.label: mt.value for mt in at.metric}["MTTR (hrs)"] != w1["MTTR (hrs)"]


def test_filters_restore_from_url_and_are_remembered(world):
    at = AppTest.from_file(str(APP_DIR / "pages/dashboard/overview.py"), default_timeout=180)
    at.session_state["user"] = load_user(world, "adm")
    at.query_params["site"] = "WBK-BAU"
    at.query_params["period"] = "last7"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.multiselect(key="f_site").value == ["WBK-BAU"]
    assert at.selectbox(key="f_period").value == "last7"
    head = next(x.value for x in at.markdown if "last 7 days" in x.value)
    assert "WBK-BAU" in head and "– 23 Sep 2026" in head
    world.expire_all()                               # remembered for the account without pressing anything
    saved = world.query(m.User).filter(m.User.username == "adm").one().default_filters
    assert saved["f_site"] == ["WBK-BAU"] and saved["f_period"] == "last7"
    # a new session without URL parameters (refresh after sign-in, another device) opens with the same filters
    at2 = run("overview", load_user(world, "adm"))
    assert at2.multiselect(key="f_site").value == ["WBK-BAU"]


def test_compare_shows_change_against_previous_period(world):
    at = AppTest.from_file(str(APP_DIR / "pages/dashboard/overview.py"), default_timeout=180)
    at.session_state["user"] = load_user(world, "adm")
    at.query_params["period"] = "last7"
    at.query_params["cmp"] = "1"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.toggle(key="f_cmp").value is True
    assert any("compared with" in x.value for x in at.markdown)
    assert any("vs previous" in c.value for c in at.caption)


def test_system_health_for_admin_only(world):
    world.add(m.AuditLog(username="system", action="backup_ok", detail="eq_dashboard_2026-09-28.dump 12M"))
    world.commit()
    at = run_path("pages/home.py", load_user(world, "adm"))
    assert not at.exception, [e.value for e in at.exception]
    labels = {mt.label: mt for mt in at.metric}
    assert "Last backup" in labels and "12M" in labels["Last backup"].delta
    vw = run_path("pages/home.py", load_user(world, "vw"))
    assert "Last backup" not in {mt.label for mt in vw.metric}


def test_hourly_pages_by_role(world):
    sm = load_user(world, "sm")                                    # Site Manager BAU
    at = run_path("pages/admin/hourly_setup.py", sm)
    assert not at.exception, [e.value for e in at.exception]
    assert at.selectbox(key="hs_site").options == ["WBK-BAU"]
    at = run_path("pages/data/hourly_input.py", sm)
    assert not at.exception
    assert any("No load factors" in w.value for w in at.warning)    # setup comes first
    world.add_all([m.LoadFactor(site="WBK-BAU", material="OB - FreeDig", material_group="OB", hauler_model="777E",
                                muatan=41), m.LoaderTarget(site="WBK-BAU", unit_id="WEX019", model="CAT6020",
                                                           material_group="OB", target_per_hour=800)])
    world.commit()
    at = run_path("pages/data/hourly_input.py", sm)
    assert not at.exception, [e.value for e in at.exception]
    assert [t.label for t in at.tabs] == ["Web input", "Excel template"]
    vw = load_user(world, "vw")
    for p in ("pages/data/hourly_input.py", "pages/admin/hourly_setup.py"):
        assert any("do not have access" in e.value for e in run_path(p, vw).error)


def test_hourly_dashboard_interactive_tabs(world):
    import datetime as dt

    import pandas as pd

    from core import hourly as H
    from db import repo
    lf = pd.DataFrame([("OB - FreeDig", "OB", "777E", 41.0)], columns=["material", "material_group", "hauler_model",
                                                                         "muatan"])
    tg = pd.DataFrame([("WEX019", "CAT6020", "OB", 800.0)], columns=["unit_id", "model", "material_group",
                                                                      "target_per_hour"])
    rows = pd.DataFrame([{"loader": "WEX019", "hauler_model": "777E", "hauler": None, "material": "OB - FreeDig",
                          "hauler_operator": "Budi", "r1": 8, "r2": 14, "r3": 6}])
    res = H.resolve(rows, lf, tg)
    repo.save_hourly(world, "WBK-BAU", dt.date(2026, 9, 20), "DS", "PJA", res.rows, "t")
    world.commit()
    at = run_path("pages/dashboard/hourly.py", load_user(world, "adm"))
    at.date_input(key="hp_date").set_value(dt.date(2026, 9, 20))
    at.segmented_control(key="hp_shift").set_value("DS")
    at.selectbox(key="hp_site").set_value("WBK-BAU")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert [t.label for t in at.tabs] == ["TV screen", "Pace", "Fleets", "Haulers & operators", "Month", "Lines"]
    assert len(at.get("plotly_chart")) >= 4                     # pace, heatmap, fleet totals, operators (+ month)


def test_hourly_dashboard_hauler_without_trips_and_zero_target(world):
    """Start of a shift: a hauler copied from the previous shift has no trips yet, and a loader has target 0.
    Both used to divide by pd.NA, which crashed the Fleets and Haulers & operators tabs."""
    import datetime as dt

    import pandas as pd

    from core import hourly as H
    from db import repo
    lf = pd.DataFrame([("OB - FreeDig", "OB", "777E", 41.0)], columns=["material", "material_group", "hauler_model",
                                                                         "muatan"])
    tg = pd.DataFrame([("WEX019", "CAT6020", "OB", 800.0), ("WEX020", "CAT6020", "OB", 0.0)],
                      columns=["unit_id", "model", "material_group", "target_per_hour"])
    rows = pd.DataFrame([
        {"loader": "WEX019", "hauler_model": "777E", "hauler": None, "material": "OB - FreeDig",
         "hauler_operator": "Budi", "r1": 8, "r2": 14},
        {"loader": "WEX019", "hauler_model": "777E", "hauler": "WHT099", "material": "OB - FreeDig",
         "hauler_operator": "Andi", "r1": 0, "r2": 0},
        {"loader": "WEX020", "hauler_model": "777E", "hauler": None, "material": "OB - FreeDig",
         "hauler_operator": "Cici", "r1": 5, "r2": 0}])
    res = H.resolve(rows, lf, tg)
    repo.save_hourly(world, "WBK-BAU", dt.date(2026, 9, 20), "DS", "PJA", res.rows, "t")
    world.commit()
    at = run_path("pages/dashboard/hourly.py", load_user(world, "adm"))
    at.date_input(key="hp_date").set_value(dt.date(2026, 9, 20))
    at.segmented_control(key="hp_shift").set_value("DS")
    at.selectbox(key="hp_site").set_value("WBK-BAU")
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_tv_preview_hourly_past_shift(world):
    import datetime as dt
    at = run_path("pages/tv/preview.py", load_user(world, "adm"))
    at.segmented_control(key="tv_screen").set_value("hourly").run()
    assert not at.exception, [e.value for e in at.exception]
    at.date_input(key="tv_h_date").set_value(dt.date(2026, 9, 20)).run()
    assert not at.exception and any("a past shift" in c.value for c in at.caption)


def test_tv_devices_hourly_report_controls(world):
    import datetime as dt

    from auth import display
    dev, _ = display.create_device(world, "BAU hourly", "WBK-BAU", None)
    dev.screen = "hourly"
    world.commit()
    at = run_path("pages/admin/display_devices.py", load_user(world, "adm"))
    assert not at.exception, [e.value for e in at.exception]
    at.segmented_control(key=f"hmode{dev.id}").set_value("Fixed date").run()
    assert not at.exception
    at.date_input(key=f"hdate{dev.id}").set_value(dt.date(2026, 9, 20)).run()
    world.expire_all()
    got = world.get(m.DisplayDevice, dev.id)
    assert got.hourly_date == dt.date(2026, 9, 20) and got.hourly_shift == "DS"


def test_unit_population_page_shows_movements(world, parsed):
    import datetime as dt
    u = parsed.units
    unit = u.loc[u["site"] == "WBK-MAS", "unit_id"].iloc[0]
    moved = u.copy()
    moved.loc[moved["unit_id"] == unit, "site"] = "WBK-BAU"
    repo.save_population(world, u, dt.date(2026, 8, 1), "a.xlsx", "a" * 64, None)
    repo.save_population(world, moved, dt.date(2026, 9, 1), "b.xlsx", "b" * 64, None)
    world.commit()
    at = run_path("pages/admin/unit_population.py", load_user(world, "adm"))
    assert not at.exception, [e.value for e in at.exception]
    assert any(t.label == "Unit movements (1)" for t in at.tabs), [t.label for t in at.tabs]
    at.text_input(key="mv_q").input(unit).run()
    assert any(f"History of {unit}" in c.value and "→ WBK-BAU" in c.value for c in at.caption), [c.value for c in at.caption]
