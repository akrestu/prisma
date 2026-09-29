"""Multi-month workbooks (e.g. a whole year) split by month; text dates; typing slips; trips entered as volume."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from core import clean, dq
from core.io import excel_date
from core.parse import split_months


def _frames():
    ev = pd.DataFrame({"Date": pd.to_datetime(["2023-01-05", "2023-01-31", "2023-02-01", "2023-03-10"]),
                       "_row": [2, 3, 4, 5]})
    fuel = pd.DataFrame({"DATE": [pd.Timestamp("2023-02-02"), None, pd.Timestamp("2023-03-01")], "_row": [2, 3, 4]})
    pop = pd.DataFrame({"Equipment": ["WHT001"]})
    return {"Eq.Event": ev, "Fuel Consume": fuel, "Populasi Unit": pop}


def test_split_months_keeps_rows_and_row_numbers():
    parts = split_months(_frames())
    assert list(parts) == [dt.date(2023, 1, 1), dt.date(2023, 2, 1), dt.date(2023, 3, 1)]
    assert parts[dt.date(2023, 1, 1)]["Eq.Event"]["_row"].tolist() == [2, 3]
    assert parts[dt.date(2023, 2, 1)]["Fuel Consume"]["_row"].tolist() == [2]
    assert parts[dt.date(2023, 1, 1)]["Fuel Consume"]["_row"].tolist() == [3]      # no date → first month, checked there
    assert all(len(p["Populasi Unit"]) == 1 for p in parts.values())                  # copied to every month


def test_text_dates_are_day_first_and_serial_plus_time_is_read():
    s = pd.Series(["01/02/23 19:59:17", "14/04/23 20:18:24", "44984 14:06:34", "2023-05-06", None], dtype=object)
    out = excel_date(s)
    assert out[0] == pd.Timestamp("2023-02-01 19:59:17")                      # 1 Feb, not 2 Jan
    assert out[1] == pd.Timestamp("2023-04-14 20:18:24")
    assert out[2] == pd.Timestamp("2023-02-27 14:06:34")
    assert out[3] == pd.Timestamp("2023-05-06") and pd.isna(out[4])


def test_shift_typing_slips():
    assert clean._shift(pd.Series(["I", "l", "II", "ll", "day"])).tolist() == ["DS", "DS", "NS", "NS", "DS"]


def test_trips_entered_as_volume_is_critical():
    n = 60
    base = pd.DataFrame({"site": "WBK-MAS", "muatan": [30.0] * n, "rit": [30.0, 60.0, 90.0] * (n // 3)})
    f = dq._rit_as_volume(base)
    assert f["rule"].tolist() == ["rit_is_volume"] and f["severity"].iloc[0] == "critical"
    trips = base.assign(rit=[1.0, 2.0, 3.0] * (n // 3))
    assert dq._rit_as_volume(trips).empty
