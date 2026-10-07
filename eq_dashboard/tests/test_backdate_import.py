"""Production Data import for backdated data: models from the Unit Population, ritase after the cutover left out."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from core import clean, dq
from core.validate import HOUR_SLOTS, SHEETS, validate
from db import models as m
from db import repo

UNITS = pd.DataFrame([("WHT026", "Hauling", "777E-KDP", "WBK-BAU"), ("WEX019", "Loading", "CAT6020", "WBK-BAU")],
                     columns=["unit_id", "type", "model", "site"])


def trips(*days: int, models: bool = True) -> pd.DataFrame:
    rows = []
    for i, d in enumerate(days):
        r = {"_row": i + 3, "Date": dt.datetime(2026, 9, d), "EqNumber": "WHT026", "Muatan": 41, "Loader": "WEX019",
             "Material": "OB - FreeDig", "Lokasi Loader": "TKM", "Disposal": "IPD", "V Distance": 40,
             "H Distance": 2600, **dict.fromkeys(HOUR_SLOTS), "06-07": 3}
        if models:
            r |= {"EqModel": "777E", "Loader Model": None}
        rows.append(r)
    return pd.DataFrame(rows)


def test_models_come_from_the_unit_population():
    r = clean.clean_ritasi(trips(1), UNITS)
    assert (r["hauler_model"] == "777E-KDP").all() and (r["loader_model"] == "CAT6020").all()
    r = clean.clean_ritasi(trips(1, models=False), UNITS)                 # columns left out of the file
    assert (r["hauler_model"] == "777E-KDP").all()
    unknown = clean.clean_ritasi(trips(1).assign(EqNumber="WDT999"), UNITS)  # unit not in the population: file value
    assert (unknown["hauler_model"] == "777E").all()


def test_model_columns_are_optional_in_the_workbook():
    trips_sheet = next(sh for sh in SHEETS if sh.name == "Hauler Trips")
    heads = [c.name for c in trips_sheet.cols if c.name not in ("EqModel", "Loader Model")]
    raw = {sh.name: pd.DataFrame([[c.name for c in sh.cols]]) for sh in SHEETS if sh.name != "Hauler Trips"}
    raw["Hauler Trips"] = pd.DataFrame([["title"] + [None] * (len(heads) - 1), heads])
    frames = validate(raw)
    assert "EqModel" in frames["Hauler Trips"] and "Loader Model" in frames["Hauler Trips"]
    raw["Hauler Trips"] = pd.DataFrame([["title"] + [None] * (len(heads) - 2), heads[:-1]])   # a real column gone
    with pytest.raises(Exception, match="missing columns"):
        validate(raw)


def test_ritase_after_the_cutover_is_reported_per_site():
    r = clean.clean_ritasi(trips(18, 19, 20, 21), UNITS)
    found = dq.combine(dq.after_cutover(r, dt.date(2026, 9, 20)))
    assert len(found) == 1 and found.loc[0, "severity"] == "info" and found.loc[0, "site"] == "WBK-BAU"
    assert "2 row(s) dated 20 Sep – 21 Sep 2026 left out" in found.loc[0, "detail"]
    assert dq.after_cutover(r, None) == [] and dq.after_cutover(r, dt.date(2026, 10, 1)) == []


def test_stored_workbook_ritase_after_the_cutover_is_deleted_once(db_session):
    s = db_session
    up = m.Upload(filename="x.xlsx", sha256="a" * 64, month=dt.date(2026, 9, 1), summary={})
    s.add(up)
    s.flush()
    for d in (19, 20, 21):
        s.add(m.FactRitase(upload_id=up.id, site="WBK-BAU", month=dt.date(2026, 9, 1), site_hauler="WBK-BAU",
                           date=dt.date(2026, 9, d), hour_slot="06-07", shift="DS", hauler="WHT026", muatan=41,
                           loader="WEX019", material_group="OB", rit=3, volume=123, unit_vol="BCM"))
    s.commit()
    assert repo.workbook_ritase_after_cutover(s).empty                     # no cutover: nothing to clean
    repo.set_setting(s, repo.CUTOVER_KEY, "2026-09-20", "admin")
    s.commit()
    left = repo.workbook_ritase_after_cutover(s)
    assert left.loc[0, "rows"] == 2 and left.loc[0, "first"] == dt.date(2026, 9, 20)
    repo.workbook_ritase_after_cutover(s, delete=True)
    s.commit()
    assert repo.workbook_ritase_after_cutover(s).empty
    assert s.query(m.FactRitase).count() == 1                              # the day before the cutover stays
