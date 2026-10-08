"""Hourly production screen: figures against the site's Excel dashboard, official + flash MTD, HTML, kiosk link."""
from __future__ import annotations

import datetime as dt
import io
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select

from core import hourly as H
from core import hourly_tv
from core.config import WIB
from core.hourly_render import render
from db import models as m
from db import repo

MST = Path(__file__).resolve().parents[2] / "Mst Hourly.xlsx"
pytestmark = pytest.mark.skipif(not MST.exists(), reason="Mst Hourly.xlsx not found")


def _seed(s, date=dt.date(2026, 9, 26), site="WBK-BAU"):
    data = MST.read_bytes()
    lf, tg = H.parse_link_muatan(data)
    tg = tg.assign(material_group="OB")
    repo.replace_site_rows(s, m.LoadFactor, site, lf, ["material", "material_group", "hauler_model", "muatan"])
    repo.replace_site_rows(s, m.LoaderTarget, site, tg, ["unit_id", "model", "material_group", "target_per_hour"])
    raw = pd.read_excel(io.BytesIO(data), sheet_name="DS", header=None, engine="calamine")
    rows = H.parse_mst_shift(raw).assign(distance_m=2000.0, remark_code="100")
    res = H.resolve(rows, lf, tg)
    assert not res.problems
    repo.save_hourly(s, site, date, "DS", "DANIEL PURBA", res.rows, "op1")
    s.commit()


def test_figures_match_the_site_excel_dashboard(db_session):
    _seed(db_session)
    d = hourly_tv.build(db_session, "WBK-BAU", dt.datetime(2026, 9, 26, 11, 40, tzinfo=WIB))
    assert (d.date, d.shift, d.slot, d.live) == (dt.date(2026, 9, 26), "DS", 6, True)
    # Dashboard DS sheet of Mst Hourly: 11-12 = 719 BCM, cumulative 4,165 BCM
    assert d.summary["Hour"]["OB"][0] == 719
    assert d.summary["Daily"]["OB"][0] == 4165
    ob = d.fleets["OB"].set_index("loader")
    assert ob.loc["WEX019", "s1"] == 328 and ob.loc["WEX008", "total"] == 822
    assert d.totals["OB"]["running"][:6] == [1, 2, 2, 2, 2, 2]
    assert d.coordinator == "DANIEL PURBA" and d.summary["Hour"]["OB"][1] == 1000     # 200 + 800 working fleets


def test_mtd_is_official_data_then_flash(world_published):
    s = world_published
    _seed(s, date=dt.date(2026, 9, 26))
    official = s.scalar(select(func.sum(m.FactRitase.volume)).where(
        m.FactRitase.site == "WBK-BAU", m.FactRitase.material_group == "OB"))
    d = hourly_tv.build(s, "WBK-BAU", dt.datetime(2026, 9, 26, 17, 30, tzinfo=WIB))
    assert d.official_until == dt.date(2026, 9, 23)
    assert d.summary["MTD"]["OB"][0] == pytest.approx(official + 4165)


def test_render_has_both_tables_and_current_hour(db_session):
    _seed(db_session)
    d = hourly_tv.build(db_session, "WBK-BAU", dt.datetime(2026, 9, 26, 11, 40, tzinfo=WIB))
    html = render(d, now=dt.datetime(2026, 9, 26, 11, 40, tzinfo=WIB))
    assert "Overburden" in html and "Coal" in html and "Running fleet" in html and "11-12" in html
    assert "class='now'" in html and "DANIEL PURBA" in html
    assert html.lower().count("<script") == 1 and "--ef" in html          # only the shrink-to-fit script


def test_render_shows_loader_operator_and_light_theme(db_session):
    _seed(db_session)
    d = hourly_tv.build(db_session, "WBK-BAU", dt.datetime(2026, 9, 26, 11, 40, tzinfo=WIB))
    ops = [o for df in d.fleets.values() if len(df) for o in df["operator"] if o]
    dark, light = (render(d, theme=k) for k in ("dark", "light"))
    assert "<th class='l'>Operator</th>" in dark and all(o in dark for o in ops)
    assert "#F7F6F2" in light and "#F7F6F2" not in dark and " light\"" in light
    assert render(d, theme="nope") == render(d, theme="dark") or "#F7F6F2" not in render(d, theme="nope")


def test_empty_shift_renders(db_session):
    d = hourly_tv.build(db_session, "WBK-MAS", dt.datetime(2026, 9, 26, 8, 0, tzinfo=WIB))
    assert d.empty and "No overburden input" in render(d)


@pytest.fixture()
def world_published(db_session, sample_bytes):
    from core import ingest as ing
    s = db_session
    ing.ingest(s, sample_bytes, "Data_Prod_2026-09.xlsb", username="t")
    for us in s.query(m.UploadSite).filter(m.UploadSite.site_code != "UNMAPPED"):
        ing.publish(s, us, None, "t")
    s.commit()
    return s


def test_tv_shows_shift_boss_and_loader_operator_names(db_session):
    _seed(db_session)
    s = db_session
    rows = repo.hourly_shift(s, "WBK-BAU", dt.date(2026, 9, 26), "DS")[1].assign(operator="Budi Santoso")
    repo.save_hourly(s, "WBK-BAU", dt.date(2026, 9, 26), "DS", "Andi Shiftboss", rows, "op1")
    s.commit()
    html = render(hourly_tv.build(s, "WBK-BAU", dt.datetime(2026, 9, 26, 11, 40, tzinfo=WIB)))
    assert "Shift boss <b>Andi Shiftboss</b>" in html
    assert "Budi Santoso" in html and ">Operator<" in html                # shared with the loader operators


def test_tv_lists_hauler_ids_per_fleet_and_hides_nan_boss(db_session):
    import pandas as pd
    s = db_session
    _seed(s)
    rows = repo.hourly_shift(s, "WBK-BAU", dt.date(2026, 9, 26), "DS")[1]
    rows.loc[rows["loader"] == "WEX019", "hauler"] = ["WHT018", "WHT019"][:int((rows["loader"] == "WEX019").sum())]
    repo.save_hourly(s, "WBK-BAU", dt.date(2026, 9, 26), "DS", "nan", rows, "op1")
    s.commit()
    d = hourly_tv.build(s, "WBK-BAU", dt.datetime(2026, 9, 26, 11, 40, tzinfo=WIB))
    ob = d.fleets["OB"].set_index("loader")
    assert ob.loc["WEX019", "hauler_ids"].startswith("WHT018") and d.coordinator == ""
    html = render(d)
    assert "WHT018" in html and "Shift boss <b>—</b>" in html and pd.notna(ob.loc["WEX019", "haulers"])


def test_remarks_show_in_their_hour_and_in_the_list(db_session):
    _seed(db_session)
    s = db_session
    sh, rows = repo.hourly_shift(s, "WBK-BAU", dt.date(2026, 9, 26), "DS")
    loader = rows["loader"].iloc[0]
    rm = pd.DataFrame([{"slot": 4, "loader": loader, "hauler": None, "code": "302", "remark": None},
                       {"slot": 2, "loader": loader, "hauler": "WHT026", "code": "402", "remark": "ban"}])
    repo.save_hourly(s, "WBK-BAU", dt.date(2026, 9, 26), "DS", sh.coordinator, rows, "op1", remarks=rm)
    s.commit()
    d = hourly_tv.build(s, "WBK-BAU", dt.datetime(2026, 9, 26, 11, 40, tzinfo=WIB))
    f = pd.concat(d.fleets.values())
    r = f[f["loader"] == loader].iloc[0]
    assert r["m4"] == "302" and r["m2"] == "402" and r["m1"] == ""
    assert d.events["hours"].tolist() == ["07-08", "09-10"]
    html = render(d, now=dt.datetime(2026, 9, 26, 11, 40, tzinfo=WIB))
    assert "class='rk'" not in html and "class='rc" not in html         # no badge row or badges any more
    assert "<i class='dot delay'></i></td>" in html and "<i class='dot down'></i></td>" in html   # a dot in the hour
    assert ">NOW<" not in html                                          # 09-10 is past
    assert "<b>Rain</b>" in html and "WHT026" in html and "— ban" in html
    ev = html.index("class=\"ev\"")                                     # full text under the fleet's table
    assert html.count("class=\"ev\"") == 1 and loader in html[ev:] and "09-10" in html[ev:]
    assert "<th class='l'>Remark</th>" not in html              # the narrow column is gone


def test_every_remark_is_shown_in_full(db_session):
    _seed(db_session)
    s = db_session
    sh, rows = repo.hourly_shift(s, "WBK-BAU", dt.date(2026, 9, 26), "DS")
    keep = rows["loader"].drop_duplicates().tolist()[:3]
    repo.save_hourly(s, "WBK-BAU", dt.date(2026, 9, 26), "DS", sh.coordinator, rows[rows["loader"].isin(keep)], "x")
    notes = [f"catatan panjang nomor {i} " * 4 for i in range(30)]
    for i, t in enumerate(notes):
        repo.add_hourly_remark(s, "WBK-BAU", dt.date(2026, 9, 26), "DS", 1 + i % 12, 1 + i % 12, keep[i % 3], None,
                               t, "x")
    s.commit()
    d = hourly_tv.build(s, "WBK-BAU", dt.datetime(2026, 9, 26, 14, 40, tzinfo=WIB))
    html = render(d, now=dt.datetime(2026, 9, 26, 14, 40, tzinfo=WIB))
    assert all(t.strip() in html for t in notes)                    # nothing dropped or cut
    assert html.count("class='fl'") == 3 and "target met" in html     # one remark block per excavator


def test_remarks_go_under_their_own_board(db_session):
    _seed(db_session)
    s = db_session
    _, rows = repo.hourly_shift(s, "WBK-BAU", dt.date(2026, 9, 26), "DS")
    first = rows.drop_duplicates("material_group").set_index("material_group")["loader"]
    repo.add_hourly_remark(s, "WBK-BAU", dt.date(2026, 9, 26), "DS", 2, 2, first["OB"], None, "catatan OB", "x")
    repo.add_hourly_remark(s, "WBK-BAU", dt.date(2026, 9, 26), "DS", 3, 3, first["CG"], None, "catatan coal", "x")
    s.commit()
    d = hourly_tv.build(s, "WBK-BAU", dt.datetime(2026, 9, 26, 11, 40, tzinfo=WIB))
    html = render(d, now=dt.datetime(2026, 9, 26, 11, 40, tzinfo=WIB))
    ob_total, cg_title, cg_total = html.index("Total BCM"), html.index("<h3>Coal</h3>"), html.index("Total t")
    assert ob_total < html.index("catatan OB") < cg_title < cg_total < html.index("catatan coal")



def test_day_pace_mtd_up_to_now_and_outlook_coloured_by_pace(db_session):
    _seed(db_session)
    s = db_session
    s.add(m.PlanProduction(site="WBK-BAU", year=2026, month=9, date=None, ob_bcm=300_000.0, coal_ton=None))
    s.commit()
    d = hourly_tv.build(s, "WBK-BAU", dt.datetime(2026, 9, 26, 11, 40, tzinfo=WIB))   # DS, hour 6 of 24 passed
    frac = d.slot / 24
    a, t, ach = d.summary["Daily"]["OB"]
    assert t == pytest.approx(10_000)                                   # 300,000 ÷ 30 days
    assert ach == pytest.approx(a / (10_000 * frac))                    # actual vs the plan of the hours passed
    _, t_mtd, _ = d.summary["MTD"]["OB"]
    assert t_mtd == pytest.approx(25 * 10_000 + 10_000 * frac)          # 25 full days + the part of the 26th
    left, t_m, done = d.summary["Outlook"]["OB"]
    assert t_m == pytest.approx(300_000) and done == pytest.approx((300_000 - left) / 300_000)
    assert d.month_pace["OB"] == pytest.approx(d.month_runrate["OB"] / 300_000)
    html = render(d, now=dt.datetime(2026, 9, 26, 11, 40, tzinfo=WIB))
    assert " so far</div>" in html and " done</div>" in html
