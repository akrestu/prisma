"""Single entry point: Data_Prod workbook bytes → all clean tables + data quality findings (no database)."""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from core import clean, dq
from core.io import excel_date, read_workbook
from core.validate import StructureError, validate


@dataclass
class Parsed:
    month: object
    units: pd.DataFrame
    events: pd.DataFrame
    stoppages: pd.DataFrame
    ritase: pd.DataFrame
    coal: pd.DataFrame          # termasuk baris cancelled (BATAL); disaring saat disimpan
    fuel: pd.DataFrame
    receipt: pd.DataFrame
    dq: pd.DataFrame
    sites: list[str] = field(default_factory=list)
    population_source: str = ""


def parse_data_prod(data: bytes, alias: dict[str, str] | None = None,
                    tank_site: dict[str, str] | None = None,
                    population: Callable[[dt.date], pd.DataFrame | None] | pd.DataFrame | None = None) -> Parsed:
    """`population` gives the units (unit_id, type, description, model, manufacturer, site) valid for the file's
    month: a DataFrame, or a function month → DataFrame (the Unit_Population version in force). Without one, the
    old 'Populasi Unit' sheet of the workbook is used."""
    frames = validate(read_workbook(data))
    month = _file_month(frames["Eq.Event"])
    units, source = None, ""
    if population is not None:
        units = population(month) if callable(population) else population
        source = units.attrs.get("source", "Unit_Population") if units is not None else ""
    if units is None or len(units) == 0:
        if "Populasi Unit" not in frames:
            raise StructureError([f"No unit population applies to {month:%B %Y}. Import a Unit_Population workbook "
                                  "(Data → Unit population) with an effective date on or before this month."])
        units, source = clean.clean_units(frames["Populasi Unit"]), "sheet 'Populasi Unit' in this file"
    events = clean.clean_events(frames["Eq.Event"], units)
    if events.empty:
        raise StructureError(["Sheet 'Eq.Event' has no data rows."])
    months = sorted(set(events["month"]))
    if len(months) > 1:
        raise StructureError([f"A file must contain one month only; found {', '.join(map(str, months))}."])
    stoppages = clean.build_stoppages(events)
    ritase = clean.clean_ritasi(frames["Ritasi Unit"], units, alias)
    coal = clean.clean_timbangan(frames["Data Timbangan"], units, alias)
    fuel_all = clean.clean_fuel(frames["Fuel Consume"], units, alias)
    fuel = fuel_all.dropna(subset=["liters"])
    receipt = clean.clean_receipt(frames["Fuel Receipt"], units, tank_site)
    findings = dq.combine(dq.check_units(units) + dq.check_events(events) + dq.check_ritasi(ritase)
                          + dq.check_timbangan(coal) + dq.check_fuel(len(fuel_all) - len(fuel), fuel, receipt))
    sites = sorted(set(events["site"]) | set(ritase["site"]) | set(coal["site"]) | set(fuel["site"])
                   | set(receipt["site"]))
    return Parsed(months[0], units, events, stoppages, ritase, coal, fuel, receipt, findings, sites, source)


def _file_month(ev_sheet: pd.DataFrame) -> dt.date:
    d = excel_date(ev_sheet["Date"]).dropna()
    if d.empty:
        raise StructureError(["Sheet 'Eq.Event' has no data rows."])
    return d.min().date().replace(day=1)


parse_eq_event = parse_data_prod  # old name, kept for scripts and tests
