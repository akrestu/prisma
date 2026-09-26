"""Data_Prod template, export round trip, file-name convention and the date/time readers."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from core import dataprod, metrics
from core.io import day_fraction, excel_date, read_workbook
from core.parse import parse_data_prod
from core.validate import SHEETS, TEMPLATE_VERSION, StructureError, template_meta, validate


def test_day_fraction_accepts_every_reader_format():
    s = pd.Series([dt.time(6, 0), dt.datetime(2026, 9, 1, 18, 30), 0.25, "07:30", None, 46266.75])
    got = day_fraction(s).round(6).tolist()
    assert got[:4] == [0.25, round(18.5 / 24, 6), 0.25, 0.3125]
    assert pd.isna(got[4]) and got[5] == 0.75


def test_excel_date_serial_and_datetime():
    s = pd.Series([46266, dt.datetime(2026, 9, 2), "2026-09-03", None])
    got = excel_date(s)
    assert [d.date() if pd.notna(d) else None for d in got] == [dt.date(2026, 9, 1), dt.date(2026, 9, 2),
                                                                 dt.date(2026, 9, 3), None]


def test_file_name_convention():
    assert dataprod.file_name(dt.date(2026, 9, 1)) == "Data_Prod_2026-09.xlsx"
    assert dataprod.month_from_name("Data_Prod_2026-09_WBK-MAS.xlsb") == dt.date(2026, 9, 1)
    assert dataprod.month_from_name("data prod 202609.xlsx") == dt.date(2026, 9, 1)
    assert dataprod.name_check("Data_Prod_2026-09.xlsb", dt.date(2026, 9, 1)) is None
    assert "says August 2026" in dataprod.name_check("Data_Prod_2026-08.xlsb", dt.date(2026, 9, 1))
    assert "convention" in dataprod.name_check("Eq.Event.xlsb", dt.date(2026, 9, 1))


def test_template_has_every_sheet_and_column_and_meta():
    raw = read_workbook(dataprod.build_template(["WBK-BAU", "WBK-MAS"]))
    frames = validate(raw)                       # passes the same check as an upload
    for sh in SHEETS:
        assert [c.name for c in sh.cols] == list(frames[sh.name].columns)[:len(sh.cols)]
    meta = template_meta(raw)
    assert meta["dataset"] == "Data_Prod" and meta["template_version"] == str(TEMPLATE_VERSION)
    with pytest.raises(StructureError, match="no data rows"):
        parse_data_prod(dataprod.build_template(["WBK-MAS"]))


def test_newer_template_version_is_refused(raw_frames):
    raw = dict(raw_frames)
    raw["_meta"] = pd.DataFrame([["template_version", str(TEMPLATE_VERSION + 1)]])
    with pytest.raises(StructureError, match="template version"):
        validate(raw)


def test_export_round_trip_gives_the_same_numbers(parsed):
    p = parsed
    t = {"units": p.units, "events": p.events, "ritase": p.ritase, "coal": p.coal[~p.coal["cancelled"]],
         "fuel": p.fuel, "receipt": p.receipt}
    q = parse_data_prod(dataprod.export_workbook(t, p.month, p.sites))
    assert q.month == p.month and q.sites == p.sites and len(q.units) == len(p.units)
    assert len(q.events) == len(p.events) and len(q.stoppages) == len(p.stoppages) == 1489
    assert q.ritase["rit"].sum() == p.ritase["rit"].sum() == 32893
    assert q.ritase["volume"].sum() == pytest.approx(p.ritase["volume"].sum())
    assert q.coal["ton"].sum() == pytest.approx(p.coal.loc[~p.coal["cancelled"], "ton"].sum())
    assert q.fuel["liters"].sum() == pytest.approx(p.fuel["liters"].sum())
    assert q.receipt["liters"].sum() == pytest.approx(1189002)
    a, b = metrics.kpis(p.events, ["site"]), metrics.kpis(q.events, ["site"])
    pd.testing.assert_frame_equal(a[["PA", "UoA"]], b[["PA", "UoA"]])
