"""Unit Population: parse, diff, template, effective-date versions, and Data_Prod without a population sheet."""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd
import pytest
from openpyxl import load_workbook

from core import dataprod
from core import population as pop
from core.io import read_workbook
from core.parse import parse_data_prod
from core.validate import StructureError
from db import repo


def test_template_round_trip_and_diff(parsed):
    units = parsed.units
    tpl = pop.build_template(["WBK-BAU", "WBK-MAS"], units, dt.date(2026, 9, 1))
    assert "Unit Population" in read_workbook(tpl)
    assert pop.meta_effective(tpl) == dt.date(2026, 9, 1)
    back = pop.parse_population(tpl)
    assert len(back.units) == len(units) and not back.duplicates
    assert pop.diff(units, back.units).empty                        # identical → no changes

    new = back.units.copy()
    new.loc[new["unit_id"] == new["unit_id"].iloc[0], "site"] = "WBK-XYZ"
    new = pd.concat([new.iloc[2:], pd.DataFrame([{"unit_id": "WNEW01", "type": "Hauling", "description": "DT",
                                                  "model": "777E", "manufacturer": "CAT", "site": "WBK-MAS"}])])
    ch = pop.diff(units, new)["change"].str.split(" ").str[0].value_counts()
    assert ch["added"] == 1 and ch["removed"] == 2


def test_parse_population_errors_and_duplicates():
    wb = load_workbook(io.BytesIO(pop.build_template(["WBK-MAS"])))
    ws = wb["Unit Population"]
    ws.append(["Hauling", "DT", "WHT 001", "777E", "CAT", "WBK-MAS"])
    ws.append(["Hauling", "DT", "WHT001", "777E", "CAT", "WBK-MAS"])     # same unit after removing the space
    ws.append(["Loading", "EX", "WEX099", "6015B", "CAT", None])
    buf = io.BytesIO()
    wb.save(buf)
    pf = pop.parse_population(buf.getvalue())
    assert pf.duplicates == ["WHT001"] and pf.without_site == ["WEX099"] and len(pf.units) == 2
    with pytest.raises(StructureError, match="Unit_Population"):
        pop.parse_population(dataprod.build_template(["WBK-MAS"]))
    assert pop.effective_from_name("Unit_Population_2026-10-15.xlsx") == dt.date(2026, 10, 15)


def test_data_prod_without_population_needs_a_version(parsed):
    t = {"events": parsed.events, "ritase": parsed.ritase, "coal": parsed.coal[~parsed.coal["cancelled"]],
         "fuel": parsed.fuel, "receipt": parsed.receipt}
    data = dataprod.export_workbook(t, parsed.month, parsed.sites)        # export has no population sheet
    assert "Populasi Unit" not in read_workbook(data)
    with pytest.raises(StructureError, match="No unit population applies to September 2026"):
        parse_data_prod(data)
    q = parse_data_prod(data, population=lambda mo: parsed.units if mo == dt.date(2026, 9, 1) else None)
    assert q.sites == parsed.sites and len(q.events) == len(parsed.events)


def test_population_versions_by_effective_date(db_session, parsed):
    s = db_session
    u = parsed.units
    moved = u.copy()
    moved.loc[moved["unit_id"] == "WEX019", "site"] = "WBK-BAU"
    repo.save_population(s, u, dt.date(2026, 8, 1), "a.xlsx", "a" * 64, None)
    repo.save_population(s, moved, dt.date(2026, 10, 1), "b.xlsx", "b" * 64, None)
    s.commit()
    assert repo.population_for(s, dt.date(2026, 7, 1)) is None                      # before any version
    sep = repo.population_for(s, dt.date(2026, 9, 1))
    assert sep.set_index("unit_id").loc["WEX019", "site"] == u.set_index("unit_id").loc["WEX019", "site"]
    assert "effective 01 Aug 2026" in sep.attrs["source"]
    assert repo.population_for(s, dt.date(2026, 10, 1)).set_index("unit_id").loc["WEX019", "site"] == "WBK-BAU"


def test_ingest_uses_population_version(db_session, sample_bytes, parsed):
    from core import ingest as ing
    s = db_session
    moved = parsed.units.copy()
    moved.loc[moved["unit_id"] == "WEX019", "site"] = "WBK-BAU"
    repo.save_population(s, moved, dt.date(2026, 9, 1), "pop.xlsx", "c" * 64, None)
    s.commit()
    ing.ingest(s, sample_bytes, "Data_Prod_2026-09.xlsb", username="t")
    s.commit()
    from db import models as m
    ev_site = s.query(m.FactEvent.site).filter(m.FactEvent.unit_id == "WEX019").distinct().all()
    assert ev_site == [("WBK-BAU",)]                                # master wins over the file's own sheet
