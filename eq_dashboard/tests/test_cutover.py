"""Hourly Production as the official ritase from the cutover date on: merge rule, mapping, setting and the TV."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from core import hourly as H
from core import tv
from db import repo
from tests.test_hourly import LF, OPS, TG, UNITS, hauler_rows

CUT = dt.date(2026, 9, 20)


def _imported(*days: int) -> pd.DataFrame:
    return pd.DataFrame([{"site": "WBK-BAU", "date": dt.date(2026, 9, d), "material_group": "OB", "rit": 10.0,
                          "volume": 410.0} for d in days], columns=H.RITASE_COLS)


def test_workbook_before_and_hourly_from_the_cutover():
    hourly = pd.DataFrame([{"site": "WBK-BAU", "date": dt.date(2026, 9, d), "material_group": "OB", "rit": 2.0,
                            "volume": 82.0} for d in (19, 20, 21)], columns=H.RITASE_COLS)
    out = H.official_ritase(_imported(18, 19, 20, 21), hourly, CUT)
    by = out.groupby("date")["volume"].sum()
    assert by[dt.date(2026, 9, 19)] == 410 and by[dt.date(2026, 9, 20)] == 82 and by[dt.date(2026, 9, 21)] == 82
    assert len(out) == 4                                  # no day counted twice
    assert H.official_ritase(_imported(19, 20), hourly, None)["volume"].sum() == 820      # no cutover: workbook only
    assert H.official_ritase(_imported(21), None, CUT).empty                               # nothing entered yet


def test_shift_lines_as_ritase_rows():
    rows = H.resolve(hauler_rows({"hauler": "WHT026", "r1": 2, "r3": 1}), LF, TG, UNITS, OPS).rows
    rit = H.as_ritase(H.to_long(rows.assign(site="WBK-BAU", date=CUT, shift="DS")))
    assert list(rit.columns) == H.RITASE_COLS and len(rit) == 2                   # hours without trips left out
    assert set(rit["hour_slot"]) == {"06-07", "08-09"} and rit["volume"].sum() == 3 * 41
    assert (rit["site_hauler"] == "WBK-BAU").all() and (rit["dist_h"] == 2600).all()


def test_cutover_setting_and_hourly_ritase(db_session):
    s = db_session
    assert repo.hourly_cutover(s) is None
    before = repo.hourly_stamp(s, ["WBK-BAU"])
    repo.set_setting(s, repo.CUTOVER_KEY, CUT.isoformat(), "admin")
    s.commit()
    assert repo.hourly_cutover(s) == CUT and repo.hourly_stamp(s, ["WBK-BAU"]) != before
    rows = H.resolve(hauler_rows({"hauler": "WHT026", "r1": 4}), LF, TG, UNITS, OPS).rows
    repo.save_hourly(s, "WBK-BAU", CUT, "DS", "", rows, "op1")
    s.commit()
    rit = repo.hourly_ritase(s, ["WBK-BAU"], CUT, CUT)
    assert rit["volume"].sum() == 4 * 41 and repo.hourly_ritase(s, ["WBK-MAS"], CUT, CUT).empty
    merged = tv._with_hourly(s, "WBK-BAU", _imported(19, 20), pd.Series([dt.date(2026, 9, 1)]))
    assert merged.groupby("date")["volume"].sum().to_dict() == {dt.date(2026, 9, 19): 410, CUT: 164}
    repo.set_setting(s, repo.CUTOVER_KEY, None, "admin")
    s.commit()
    assert repo.hourly_cutover(s) is None
    assert len(tv._with_hourly(s, "WBK-BAU", _imported(19, 20), pd.Series([dt.date(2026, 9, 1)]))) == 2
