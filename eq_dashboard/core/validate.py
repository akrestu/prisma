"""Data_Prod workbook specification (single source of truth) and structure validation.

The same column list drives three things: the upload check, the downloadable template and the export, so they can
never drift apart. Extra columns in a workbook are allowed and ignored.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.io import frame

DATASET = "Data_Prod"
TEMPLATE_VERSION = 1
META_SHEET = "_meta"
HOUR_SLOTS = ["06-07", "07-08", "08-09", "09-10", "10-11", "11-12", "12-13", "13-14", "14-15", "15-16",
              "16-17", "17-18", "18-19", "19-20", "20-21", "21-22", "22-23", "23-00", "00-01", "01-02",
              "02-03", "03-04", "04-05", "05-06"]


@dataclass(frozen=True)
class Col:
    name: str
    kind: str          # text | date | time | datetime | number | int | list
    desc: str
    example: object = None
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Sheet:
    name: str
    header_row: int    # 0-based row that holds the column names
    purpose: str
    cols: tuple[Col, ...]


SHEETS: tuple[Sheet, ...] = (
    Sheet("Populasi Unit", 0, "Unit master: one row per equipment. The Site column decides which site owns the unit.", (
        Col("Type", "text", "Equipment type (Hauling, Loading, Dozing, …)", "Hauling"),
        Col("Description", "text", "Short description", "Dump Truck"),
        Col("Equipment", "text", "Unit ID, unique (spaces are removed on import)", "WHT026"),
        Col("Model", "text", "Unit model", "777E"),
        Col("Manufacturer", "text", "Manufacturer", "Caterpillar"),
        Col("Site", "list", "Site code; units without a site stay UNMAPPED until an Admin maps them", "WBK-MAS"),
    )),
    Sheet("Eq.Event", 0, "Time events per unit and shift: what each unit did, from when to when.", (
        Col("Date", "date", "Production date (one month per file)", "2026-09-01"),
        Col("Shift", "list", "DS (day) or NS (night); day/night are also accepted", "DS", ("DS", "NS")),
        Col("Unit ID", "text", "Unit ID as in Populasi Unit", "WHT026"),
        Col("Operator", "text", "Operator name (optional)", "Budi S."),
        Col("Jam Awal", "time", "Start time (HH:MM)", "06:00"),
        Col("Jam Akhir", "time", "End time (HH:MM)", "07:30"),
        Col("Total Jam", "number", "Duration in hours (0–24)", 1.5),
        Col("HM awal", "number", "Hour meter at start", 1392.1),
        Col("HM Akhir", "number", "Hour meter at end", 1393.6),
        Col("Status", "list", "Operating, Idle, Standby, SM (scheduled down) or USM (unscheduled down)", "Operating",
            ("Operating", "Idle", "Standby", "SM", "USM")),
        Col("Reason", "text", "3-digit reason code + text: 1xx operating, 2xx idle, 3xx standby, 4xx USM, 5xx SM",
            "101 LOADING"),
    )),
    Sheet("Ritasi Unit", 1, "Trips per hauler × loader × material, counted per production hour (06-07 … 05-06).", (
        Col("Date", "date", "Production date", "2026-09-01"),
        Col("EqNumber", "text", "Hauler unit ID", "WHT026"),
        Col("EqModel", "text", "Hauler model", "777E"),
        Col("Muatan", "number", "Load per trip (BCM for OB, ton for coal)", 41),
        Col("Loader", "text", "Loader unit ID (production is credited to the loader's site)", "WEX015"),
        Col("Loader Model", "text", "Loader model", "CAT6015B"),
        Col("Material", "text", "Starts with OB or CG (e.g. 'OB - FreeDig', 'CG - Seam UP3')", "OB - FreeDig"),
        Col("Lokasi Loader", "text", "Pit / loading point", "PIT ALAM 1-3"),
        Col("Disposal", "text", "Dumping point", "DISPOSAL A"),
        Col("V Distance", "number", "Vertical haul distance (m)", 35),
        Col("H Distance", "number", "Horizontal haul distance (m)", 1800),
        *(Col(h, "int", f"Trips in hour {h}", None) for h in HOUR_SLOTS),
    )),
    Sheet("Data Timbangan", 0, "Weighbridge coal tickets. Tickets with supplier BATAL are excluded.", (
        Col("Date", "date", "Production date", "2026-09-01"),
        Col("No. ID.", "text", "Ticket number", "CG-M090000811"),
        Col("Nama Supplier", "text", "Supplier; BATAL = cancelled ticket", "WBK"),
        Col("Nama Product", "text", "Product; the seam is read from it", "Seam UP3"),
        Col("Tanggal / Jam Masuk", "datetime", "Time in (date and time)", "2026-09-01 10:13"),
        Col("Tanggal / Jam Keluar", "datetime", "Time out (date and time)", "2026-09-01 10:25"),
        Col("Loader", "text", "Loader unit ID (tonnage is credited to its site)", "WEX015"),
        Col("Shift", "list", "DS or NS; day/night also accepted", "DS", ("DS", "NS")),
        Col("Convert DT", "text", "Dump truck unit ID", "WDT017"),
        Col("H Distance", "number", "Horizontal haul distance (m)", 2500),
        Col("Tone", "number", "Net weight in ton", 28.5),
        Col("V Distance", "number", "Vertical haul distance (m)", 40),
    )),
    Sheet("Fuel Consume", 0, "Fuel given to each unit.", (
        Col("DATE", "date", "Date", "2026-09-01"),
        Col("SHIFT", "list", "I (day) or II (night); DS/NS also accepted", "I", ("I", "II")),
        Col("MODEL", "text", "Unit model", "CGE37084R"),
        Col("UNIT", "text", "Unit ID", "WDT027"),
        Col("TIME", "time", "Time of refuelling (HH:MM)", "07:10"),
        Col("FLUID CONSUMPTION", "number", "Litres", 159),
    )),
    Sheet("Fuel Receipt", 0, "Fuel received per delivery note.", (
        Col("DATE_RECEIPT", "date", "Date received", "2026-09-03"),
        Col("SHIFT", "list", "I or II", "I", ("I", "II")),
        Col("LOCATION", "text", "Vendor / location", "PT. TBM"),
        Col("OPERATOR", "text", "Receiving operator", "Dendy K."),
        Col("UNIT", "text", "Fuel truck or tank ID (tanks are mapped to a site by the Admin)", "WFT003"),
        Col("DELIVERY NOTE", "text", "Delivery note number", "WBK/26/09/003"),
        Col("DELIVERY NOTE_VOLUME", "number", "Litres on the delivery note", 16500),
    )),
)
SHEET_BY_NAME = {sh.name: sh for sh in SHEETS}
# legacy view used by older code: sheet -> (header row, required columns)
SPEC: dict[str, tuple[int, list[str]]] = {sh.name: (sh.header_row, [c.name for c in sh.cols]) for sh in SHEETS}


class StructureError(ValueError):
    """The workbook does not follow the Data_Prod format. `problems` holds one message per issue."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("File structure is not valid:\n- " + "\n- ".join(problems))


def template_meta(raw: dict[str, pd.DataFrame]) -> dict[str, str]:
    """Key/value pairs from the hidden _meta sheet of a WANPIS template or export ({} for other workbooks)."""
    m = raw.get(META_SHEET)
    if m is None or m.shape[1] < 2:
        return {}
    return {str(k).strip(): str(v).strip() for k, v in zip(m.iloc[:, 0], m.iloc[:, 1], strict=True) if pd.notna(k)}


def validate(raw: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Return a framed DataFrame per sheet, or raise StructureError listing every problem at once."""
    problems, frames = [], {}
    meta = template_meta(raw)
    ver = meta.get("template_version")
    if ver and ver.isdigit() and int(ver) > TEMPLATE_VERSION:
        problems.append(f"This file was made with template version {ver}; this app reads up to version "
                        f"{TEMPLATE_VERSION}. Update the app or download the current template.")
    for sh in SHEETS:
        if sh.name not in raw:
            problems.append(f"Sheet '{sh.name}' was not found (sheet names must match the template exactly).")
            continue
        if len(raw[sh.name]) <= sh.header_row:
            problems.append(f"Sheet '{sh.name}' is empty: the column names belong in row {sh.header_row + 1}.")
            continue
        df = frame(raw[sh.name], sh.header_row)
        missing = [c.name for c in sh.cols if c.name not in df.columns]
        if missing:
            problems.append(f"Sheet '{sh.name}' (row {sh.header_row + 1}) is missing columns: {', '.join(missing)}.")
        frames[sh.name] = df
    if problems:
        raise StructureError(problems)
    return frames
