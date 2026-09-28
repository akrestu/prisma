"""Hourly production: production hour, Link Muatan import, resolving rows, template round trip, storage."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from core import dataprod
from core import hourly as H
from core.validate import StructureError
from db import repo

MST = Path(__file__).resolve().parents[2] / "Mst Hourly.xlsx"
LF = pd.DataFrame([("OB - FreeDig", "OB", "777E", 41.0), ("OB - MUD", "OB", "773E", 12.0),
                   ("CG - Coal Getting", "CG", "CWE370Q", 22.5)],
                  columns=["material", "material_group", "hauler_model", "muatan"])
TG = pd.DataFrame([("WEX019", "CAT6020", "OB", 800.0), ("WEX010", "SK200", "CG", 200.0)],
                  columns=["unit_id", "model", "material_group", "target_per_hour"])


def rows(**extra):
    base = {"loader": "WEX019", "operator": "Zainudin", "material": "OB - FreeDig", "hauler_model": "777E",
            "pit": "TKM", "disposal": "IPD Atas", "distance_m": 2600, "r1": 8, "r2": 14, "remark_code": "100",
            "remark": None}
    return pd.DataFrame([{**base, **extra}])


@pytest.mark.parametrize("hhmm,expected", [
    ((6, 0), (dt.date(2026, 9, 26), "DS", 1, "06-07")), ((17, 59), (dt.date(2026, 9, 26), "DS", 12, "17-18")),
    ((18, 0), (dt.date(2026, 9, 26), "NS", 1, "18-19")), ((23, 30), (dt.date(2026, 9, 26), "NS", 6, "23-00")),
])
def test_production_hour(hhmm, expected):
    d, s, k = H.production_hour(dt.datetime(2026, 9, 26, *hhmm))
    assert (d, s, k, H.slot_label(s, k)) == expected


def test_night_shift_after_midnight_belongs_to_previous_date():
    assert H.production_hour(dt.datetime(2026, 9, 27, 2, 30)) == (dt.date(2026, 9, 26), "NS", 9)
    assert H.production_hour(dt.datetime(2026, 9, 27, 5, 59)) == (dt.date(2026, 9, 26), "NS", 12)


@pytest.mark.skipif(not MST.exists(), reason="Mst Hourly.xlsx not found")
def test_link_muatan_from_real_workbook():
    lf, tg = H.parse_link_muatan(MST.read_bytes())
    look = lf.set_index(["material", "hauler_model"])["muatan"]
    assert look[("OB - FreeDig", "777E")] == 41 and look[("CG - Coal Getting", "CWE370Q")] == 22.5
    assert set(lf["material_group"]) == {"OB", "CG"} and (lf["muatan"] > 0).all()
    assert tg.set_index("unit_id").loc["WEX019", "target_per_hour"] == 800 and len(tg) == 22


def test_resolve_fills_load_and_target_and_flags_problems():
    ok = H.resolve(rows(), LF, TG)
    r = ok.rows.iloc[0]
    assert not ok.problems and r["muatan"] == 41 and r["target_per_hour"] == 800 and r["loader_model"] == "CAT6020"
    bad = H.resolve(pd.concat([rows(hauler_model="999X"), rows(r3=75)]), LF, TG)
    assert any("no load factor" in p for p in bad.problems) and any("between 0 and 60" in p for p in bad.problems)
    empty = H.resolve(rows(loader=None, r1=None, r2=None), LF, TG)       # blank lines are dropped, not errors
    assert empty.rows.empty and not empty.problems


def test_template_round_trip_and_hour_headers():
    tpl = H.build_template("WBK-BAU", dt.date(2026, 9, 26), "NS", LF, TG, H.resolve(rows(), LF, TG).rows, "D. Purba")
    hf = H.parse_template(tpl)
    assert (hf.site, hf.date, hf.shift, hf.coordinator) == ("WBK-BAU", dt.date(2026, 9, 26), "NS", "D. Purba")
    assert hf.rows.loc[0, "loader"] == "WEX019" and pd.isna(hf.rows.loc[0, "r1"])   # lines pre-filled, no trips
    with pytest.raises(StructureError, match="Hourly"):     # a Data_Prod workbook is not an hourly sheet
        H.parse_template(dataprod.build_template(["WBK-BAU"]))


def test_volume_per_hour():
    res = H.resolve(rows(), LF, TG).rows.assign(site="WBK-BAU", date=dt.date(2026, 9, 26), shift="DS")
    long = H.to_long(res)
    by = long.set_index("hour_slot")["volume"]
    assert by["06-07"] == 8 * 41 and by["07-08"] == 14 * 41 and by["08-09"] == 0


def test_save_replace_and_previous_lines(db_session):
    s = db_session
    d = dt.date(2026, 9, 26)
    r = H.resolve(pd.concat([rows(), rows(loader="WEX010", material="CG - Coal Getting", hauler_model="CWE370Q")]),
                  LF, TG).rows
    repo.save_hourly(s, "WBK-BAU", d, "DS", "D. Purba", r, "op1")
    s.commit()
    sh, got = repo.hourly_shift(s, "WBK-BAU", d, "DS")
    assert sh.coordinator == "D. Purba" and len(got) == 2 and got.loc[0, "r2"] == 14
    repo.save_hourly(s, "WBK-BAU", d, "DS", "D. Purba", r.iloc[:1], "op1")      # saving again replaces the sheet
    s.commit()
    assert len(repo.hourly_shift(s, "WBK-BAU", d, "DS")[1]) == 1
    nxt = repo.previous_lines(s, "WBK-BAU", d, "NS")
    assert nxt.loc[0, "loader"] == "WEX019" and pd.isna(nxt.loc[0, "r1"])
    rng = repo.hourly_range(s, ["WBK-BAU"], d, d)
    assert len(rng) == 1 and rng.loc[0, "shift"] == "DS"
