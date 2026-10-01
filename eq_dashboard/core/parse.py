"""Single entry point: Production Data workbook bytes → all clean tables + data quality findings (no database)."""
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
    month: a DataFrame, or a function month → DataFrame (the Unit Population version in force). Without one, the
    old 'Unit Population' sheet of the workbook is used. The file must hold one month (see `parse_months`)."""
    return parse_frames(validate(read_workbook(data)), alias, tank_site, population)


# the production date of each data sheet: a multi-month workbook is split on these
DATE_COLS = {"Equipment Events": "Date", "Hauler Trips": "Date", "Coal Weighbridge": "Date", "Fuel Consumption": "DATE",
             "Fuel Receipts": "DATE_RECEIPT"}


@dataclass
class MonthResult:
    month: dt.date
    parsed: Parsed | None = None
    problems: list[str] = field(default_factory=list)


def split_months(frames: dict[str, pd.DataFrame]) -> dict[dt.date, dict[str, pd.DataFrame]]:
    """Validated frames → one set of frames per month of Equipment Events. Rows of other sheets go to the month of their own
    date; rows without a readable date go to the first month, where the usual checks report them. Sheets without a
    date (Unit Population) are copied to every month. Excel row numbers (_row) are kept, so findings still point to
    the right row of the uploaded file."""
    ev_month = excel_date(frames["Equipment Events"]["Date"]).dt.to_period("M")
    months = sorted(ev_month.dropna().unique())
    if not months:
        raise StructureError(["Sheet 'Equipment Events' has no data rows."])
    out: dict[dt.date, dict[str, pd.DataFrame]] = {}
    for per in months:
        mo = per.to_timestamp().date()
        part = {}
        for name, df in frames.items():
            col = DATE_COLS.get(name)
            if col is None or col not in df:
                part[name] = df
                continue
            p = excel_date(df[col]).dt.to_period("M")
            keep = (p == per) | (p.isna() & (per == months[0]))
            part[name] = df[keep.to_numpy()].reset_index(drop=True)
        out[mo] = part
    return out


def parse_months(data: bytes, alias: dict[str, str] | None = None, tank_site: dict[str, str] | None = None,
                 population: Callable[[dt.date], pd.DataFrame | None] | pd.DataFrame | None = None
                 ) -> list[MonthResult]:
    """A workbook with one or many months (e.g. a whole year) → one result per month. The structure is checked once
    for the whole file (StructureError); a month that cannot be read gets its problems instead of failing the file."""
    out = []
    for mo, part in split_months(validate(read_workbook(data))).items():
        try:
            out.append(MonthResult(mo, parse_frames(part, alias, tank_site, population)))
        except StructureError as e:
            out.append(MonthResult(mo, problems=e.problems))
    return out


def parse_frames(frames: dict[str, pd.DataFrame], alias: dict[str, str] | None = None,
                 tank_site: dict[str, str] | None = None,
                 population: Callable[[dt.date], pd.DataFrame | None] | pd.DataFrame | None = None) -> Parsed:
    month = _file_month(frames["Equipment Events"])
    units, source = None, ""
    if population is not None:
        units = population(month) if callable(population) else population
        source = units.attrs.get("source", "Unit Population") if units is not None else ""
    # the published-data fallback knows only sites that already have published data; the file's own unit sheet
    # (older files) is complete, so it wins over the fallback
    weak = units is not None and units.attrs.get("fallback") and "Unit Population" in frames
    if units is None or len(units) == 0 or weak:
        if "Unit Population" not in frames:
            raise StructureError([f"No unit population applies to {month:%B %Y}. Import a Unit Population workbook "
                                  "(Input & upload → Unit Population) with an effective date on or before this month."])
        units, source = clean.clean_units(frames["Unit Population"]), "sheet 'Unit Population' in this file"
    events = clean.clean_events(frames["Equipment Events"], units)
    if events.empty:
        raise StructureError(["Sheet 'Equipment Events' has no data rows."])
    months = sorted(set(events["month"]))
    if len(months) > 1:
        raise StructureError([f"This data holds more than one month ({', '.join(map(str, months))}); "
                              "use parse_months to read it month by month."])
    stoppages = clean.build_stoppages(events)
    ritase = clean.clean_ritasi(frames["Hauler Trips"], units, alias)
    coal = clean.clean_timbangan(frames["Coal Weighbridge"], units, alias)
    fuel_all = clean.clean_fuel(frames["Fuel Consumption"], units, alias)
    fuel = fuel_all.dropna(subset=["liters"])
    receipt = clean.clean_receipt(frames["Fuel Receipts"], units, tank_site)
    findings = dq.combine(dq.check_units(units) + dq.check_events(events) + dq.check_ritasi(ritase)
                          + dq.check_timbangan(coal) + dq.check_fuel(len(fuel_all) - len(fuel), fuel, receipt))
    sites = sorted(set(events["site"]) | set(ritase["site"]) | set(coal["site"]) | set(fuel["site"])
                   | set(receipt["site"]))
    return Parsed(months[0], units, events, stoppages, ritase, coal, fuel, receipt, findings, sites, source)


def _file_month(ev_sheet: pd.DataFrame) -> dt.date:
    d = excel_date(ev_sheet["Date"]).dropna()
    if d.empty:
        raise StructureError(["Sheet 'Equipment Events' has no data rows."])
    return d.min().date().replace(day=1)


parse_eq_event = parse_data_prod  # old name, kept for scripts and tests
