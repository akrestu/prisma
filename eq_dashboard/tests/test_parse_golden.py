"""Golden test: hasil aplikasi harus sama dengan perhitungan Excel & angka yang disepakati di plan."""
from __future__ import annotations

import datetime as dt

import pytest

from core import clean, metrics
from core.io import frame
from core.validate import StructureError, validate


def test_weekly_pa_uoa_match_summary_sheet(parsed, raw_frames):
    # Summary!A1:H5 = Weekly, R, I, S, D, Total, PA, UoA (definisi minggu lama)
    summ = frame(raw_frames["Summary"], 0).iloc[:4]
    ev = clean.clean_events(frame(raw_frames["Eq.Event"], 0), parsed.units, clean.week_of_legacy)
    got = metrics.kpis(ev, ["week"])
    for _, row in summ.iterrows():
        assert got.loc[row["Weekly"], "PA"] == pytest.approx(float(row["PA"]), abs=1e-9)
        assert got.loc[row["Weekly"], "UoA"] == pytest.approx(float(row["UoA"]), abs=1e-9)


def test_production_fuel_totals(parsed):
    r = parsed.ritase
    assert r["rit"].sum() == 32893
    assert r.loc[r.material_group == "OB", "volume"].sum() == pytest.approx(778796)
    assert r.loc[r.material_group == "CG", "volume"].sum() == pytest.approx(95124)
    assert parsed.coal["ton"].sum() == pytest.approx(94855.44)
    assert parsed.coal.loc[~parsed.coal.cancelled, "ton"].sum() == pytest.approx(94709.04)
    assert parsed.fuel["liters"].sum() == pytest.approx(1380293)
    assert parsed.receipt["liters"].sum() == pytest.approx(1189002)


def test_site_split(parsed):
    k = metrics.kpis(parsed.events, ["site"])
    assert k.loc["WBK-MAS", "PA"] == pytest.approx(0.7107, abs=5e-5)
    assert k.loc["WBK-BAU", "PA"] == pytest.approx(0.5449, abs=5e-5)
    total = metrics.kpis(parsed.events)
    assert total["T"].iloc[0] == pytest.approx(k["T"].sum())
    assert total["PA"].iloc[0] == pytest.approx(0.6533, abs=5e-5)
    assert total["UoA"].iloc[0] == pytest.approx(0.4734, abs=5e-5)


def test_reliability(parsed):
    r = metrics.reliability(parsed.events, parsed.stoppages).iloc[0]
    assert r["stoppages"] == 1489
    assert r["MTBS"] == pytest.approx(20.52, abs=0.01)
    assert r["MTTR"] == pytest.approx(23.01, abs=0.01)
    assert r["SchedDown"] == pytest.approx(0.124, abs=5e-4)
    # jam stoppage = jam down
    assert parsed.stoppages["hours"].sum() == pytest.approx(metrics.time_buckets(parsed.events)["D"].iloc[0])


def test_last_complete_day_mas(parsed):
    cd = metrics.complete_days(parsed.events[parsed.events.site == "WBK-MAS"])
    assert cd[cd].index.max() == dt.date(2026, 9, 22)
    assert not cd[dt.date(2026, 9, 23)]


def test_month_and_sites(parsed):
    assert parsed.month == dt.date(2026, 9, 1)
    assert parsed.sites == ["UNMAPPED", "WBK-BAU", "WBK-MAS"]


def test_structure_missing_sheet_and_column(raw_frames):
    broken = dict(raw_frames)
    broken.pop("Data Timbangan")
    ev = broken["Eq.Event"].copy()
    ev.iloc[0] = ev.iloc[0].replace("Status", "Stat")
    broken["Eq.Event"] = ev
    with pytest.raises(StructureError) as e:
        validate(broken)
    text = str(e.value)
    assert "Data Timbangan" in text and "Status" in text
