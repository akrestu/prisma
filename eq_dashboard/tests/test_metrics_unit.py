"""Unit test metrik dengan data kecil buatan."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from core import clean, metrics

D1, D2 = dt.date(2026, 9, 1), dt.date(2026, 9, 2)


def ev(rows):
    """rows: (unit, date, shift, status, hours, reason_code, hm)"""
    df = pd.DataFrame(rows, columns=["unit_id", "date", "shift", "status", "hours", "reason_code", "hm_start"])
    df["category"] = df["status"].map({"Operating": "R", "Idle": "I", "Standby": "S", "SM": "D", "USM": "D"}).fillna("N")
    df["reason_text"] = df["reason_code"].astype(str)
    df["site"], df["type"], df["model"], df["month"] = "A", "Hauling", "777E", dt.date(2026, 9, 1)
    df["seq"] = df.groupby("unit_id").cumcount()
    return df


def test_availability_formulas():
    e = ev([("U1", D1, "DS", "Operating", 6, 102, 0), ("U1", D1, "DS", "Idle", 2, 205, 0),
            ("U1", D1, "DS", "Standby", 2, 301, 0), ("U1", D1, "DS", "USM", 2, 402, 0)])
    k = metrics.kpis(e).iloc[0]
    assert k["PA"] == pytest.approx(10 / 12)
    assert k["UoA"] == pytest.approx(8 / 10)
    assert k["MA"] == pytest.approx(8 / 10)
    assert k["EU"] == pytest.approx(8 / 12)


def test_no_data_rows_are_ignored():
    e = ev([("U1", D1, "DS", "Operating", 12, 102, 0), ("U1", D1, "NS", None, 0, None, 0)])
    assert metrics.kpis(e)["T"].iloc[0] == 12


def test_stoppage_spans_shifts_and_counts_once():
    e = ev([("U1", D1, "DS", "Operating", 6, 102, 0), ("U1", D1, "DS", "USM", 6, 402, 0),
            ("U1", D1, "NS", "USM", 12, 402, 0), ("U1", D2, "DS", "SM", 4, 502, 0),
            ("U1", D2, "DS", "Operating", 8, 102, 0), ("U1", D2, "NS", "SM", 12, 502, 0)])
    st = clean.build_stoppages(e)
    assert len(st) == 2
    assert st.iloc[0]["hours"] == 22 and st.iloc[0]["sm_hours"] == 4 and st.iloc[0]["usm_hours"] == 18
    r = metrics.reliability(e, st).iloc[0]
    assert r["MTBS"] == pytest.approx(14 / 2)
    assert r["MTTR"] == pytest.approx(34 / 2)
    assert r["MTBF"] == pytest.approx(14 / 1)
    assert r["SchedDown"] == pytest.approx(16 / 34)


def test_pm_accuracy():
    e = ev([("U1", D1, "DS", "SM", 4, 502, 1000), ("U1", D1, "DS", "Operating", 8, 102, 1004),
            ("U1", D2, "DS", "SM", 4, 502, 1240), ("U1", D2, "DS", "Operating", 8, 102, 1244),
            ("U1", D2, "NS", "SM", 4, 502, 1600)])
    iv = pd.DataFrame({"model": ["777E"], "interval_hm": [250.0], "tolerance_pct": [10.0]})
    r = metrics.pm_accuracy(e, iv).iloc[0]
    assert r["pm_events"] == 3 and r["assessable"] == 2 and r["accurate"] == 1  # 240 ok, 360 terlambat
    assert r["PMAccuracy"] == pytest.approx(0.5)


def test_week_definition():
    days = pd.Series([1, 7, 8, 14, 15, 21, 22, 31])
    assert clean.week_of(days).tolist() == ["Week 1"] * 2 + ["Week 2"] * 2 + ["Week 3"] * 2 + ["Week 4"] * 2
