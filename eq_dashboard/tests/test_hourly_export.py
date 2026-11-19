"""Hourly Production export for a manual review: shifts, lines, trips per hour and remarks in one workbook."""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd

from core import hourly as H
from core import hourly_export as HX
from db import repo

from .test_hourly import LF, TG, rows


def test_export_holds_every_shift_line_hour_and_remark(db_session):
    s = db_session
    d = dt.date(2026, 9, 26)
    r = H.resolve(pd.concat([rows(), rows(loader="WEX010", material="CG - Coal Getting", hauler_model="CWE370Q")]),
                  LF, TG).rows
    rm = pd.DataFrame([{"slot": 2, "loader": "WEX019", "hauler": None, "code": "401", "remark": "hujan"}])
    repo.save_hourly(s, "WBK-BAU", d, "DS", "D. Purba", r, "op1", remarks=rm)
    repo.save_hourly(s, "WBK-BAU", d, "NS", "", r.iloc[:1], "op2")
    repo.save_hourly(s, "WBK-BAU", d + dt.timedelta(days=5), "DS", "", r, "op1")   # outside the range
    s.commit()

    data = HX.load(s, ["WBK-BAU"], d, d + dt.timedelta(days=1))
    f = HX.frames(data)
    sh, lines, per, rem = f["Shifts"], f["Lines"], f["Per hour"], f["Remarks"]
    assert sh[["Shift", "Lines", "Status"]].values.tolist() == [["DS", 2, "DRAFT"], ["NS", 1, "DRAFT"]]
    assert sh["Trips"].sum() == lines["Trips"].sum() == per["Trips"].sum()
    assert sh.loc[0, "OB (BCM)"] > 0 and sh.loc[0, "Coal (t)"] > 0 and sh.loc[1, "Coal (t)"] == 0
    assert "H2 (07-08 | 19-20)" in lines.columns and len(lines) == 3
    assert lines["Volume (BCM / t)"].sum() == per["Volume (BCM / t)"].sum()
    assert set(per.loc[per["Shift"] == "NS", "Hour"]) <= set(H.SLOTS["NS"])      # NS hours are NS clock hours
    assert rem[["Shift", "Hour", "Loader", "Code"]].values.tolist() == [["DS", "07-08", "WEX019", "401"]]

    xl = pd.read_excel(io.BytesIO(HX.workbook(data, ["WBK-BAU"], d, d + dt.timedelta(days=1))), sheet_name=None)
    assert list(xl) == ["About", "Shifts", "Lines", "Per hour", "Remarks"]
    assert len(xl["Lines"]) == 3 and xl["Shifts"]["Trips"].sum() == sh["Trips"].sum()
    assert HX.file_name(["WBK-BAU"], d, d) == "Hourly_Review_WBK-BAU_20260926-20260926.xlsx"


def test_export_of_an_empty_range_still_opens(db_session):
    xl = pd.read_excel(io.BytesIO(HX.workbook(HX.load(db_session, ["WBK-BAU"], dt.date(2026, 1, 1),
                                                      dt.date(2026, 1, 31)), ["WBK-BAU"], dt.date(2026, 1, 1),
                                              dt.date(2026, 1, 31))), sheet_name=None)
    assert all(len(xl[k]) == 0 for k in ("Shifts", "Lines", "Per hour", "Remarks"))
    assert "Site" in xl["Lines"].columns
