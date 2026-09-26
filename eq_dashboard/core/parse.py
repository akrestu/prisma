"""Satu pintu: bytes file Eq.Event → semua tabel bersih + temuan DQ (tanpa database)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from core import clean, dq
from core.io import read_workbook
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


def parse_eq_event(data: bytes, alias: dict[str, str] | None = None,
                   tank_site: dict[str, str] | None = None) -> Parsed:
    frames = validate(read_workbook(data))
    units = clean.clean_units(frames["Populasi Unit"])
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
    return Parsed(months[0], units, events, stoppages, ritase, coal, fuel, receipt, findings, sites)
