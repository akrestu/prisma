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
    assert "OVERBURDEN" in html and "COAL" in html and "Running fleet" in html and "11-12" in html
    assert "class='now'" in html and "DANIEL PURBA" in html and "<script" not in html.lower()


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
