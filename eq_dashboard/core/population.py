"""Unit_Population workbook: master list of units and their site, versioned by an effective date. No database here.

One sheet with the same columns as the old 'Populasi Unit' sheet of Data_Prod. A version applies from its
effective date until the next version; a Data_Prod month uses the newest version effective on or before the
month's last day, so re-importing an old month keeps the population that was valid then.
"""
from __future__ import annotations

import datetime as dt
import io
from dataclasses import dataclass

import pandas as pd
from openpyxl import Workbook

from core import clean
from core.io import frame, read_workbook
from core.validate import META_SHEET, POPULATION, StructureError

DATASET = "Unit_Population"
SHEET_NAMES = ("Unit_Population", "Populasi Unit")   # new name first; the old Data_Prod sheet name is accepted
COLS = ["unit_id", "type", "description", "model", "manufacturer", "site"]


@dataclass
class PopulationFile:
    units: pd.DataFrame          # clean: unit_id, type, description, model, manufacturer, site
    duplicates: list[str]        # unit IDs listed more than once (first one kept)
    without_site: list[str]


def parse_population(data: bytes) -> PopulationFile:
    raw = read_workbook(data)
    name = next((n for n in SHEET_NAMES if n in raw), None)
    if name is None:
        raise StructureError([f"Sheet '{SHEET_NAMES[0]}' was not found (the old name 'Populasi Unit' also works)."])
    df = frame(raw[name], 0)
    missing = [c.name for c in POPULATION.cols if c.name not in df.columns]
    if missing:
        raise StructureError([f"Sheet '{name}' (row 1) is missing columns: {', '.join(missing)}."])
    ids = clean._ids(df["Equipment"])
    dups = sorted(set(ids[ids.duplicated() & ids.notna()]))
    units = clean.clean_units(df)
    if units.empty:
        raise StructureError([f"Sheet '{name}' has no units."])
    return PopulationFile(units[COLS], dups, sorted(units.loc[units["site"] == "UNMAPPED", "unit_id"]))


def diff(old: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """What changes against the previous version: added, removed, moved (site) or changed (type/model)."""
    if old is None or old.empty:
        return new.assign(change="added")[["change", *COLS]]
    o, n = old.set_index("unit_id"), new.set_index("unit_id")
    rows = [n.loc[sorted(set(n.index) - set(o.index))].assign(change="added"),
            o.loc[sorted(set(o.index) - set(n.index))].assign(change="removed")]
    both = sorted(set(o.index) & set(n.index))
    moved = [u for u in both if o.loc[u, "site"] != n.loc[u, "site"]]
    rows.append(n.loc[moved].assign(change=[f"moved from {o.loc[u, 'site']}" for u in moved]))
    changed = [u for u in both if u not in moved and any(
        str(o.loc[u, c]) != str(n.loc[u, c]) for c in ("type", "model", "description", "manufacturer"))]
    rows.append(n.loc[changed].assign(change="type/model changed"))
    out = pd.concat([r for r in rows if len(r)], axis=0) if any(len(r) for r in rows) else pd.DataFrame()
    return out.reset_index()[["change", *COLS]] if len(out) else pd.DataFrame(columns=["change", *COLS])


def build_template(sites: list[str], units: pd.DataFrame | None = None, effective: dt.date | None = None) -> bytes:
    """Unit_Population workbook in the template style (README, yellow headers with notes, Site drop-down)."""
    from core import dataprod  # shares the styling helpers
    wb = Workbook()
    dataprod._readme(wb, "PRISMA · Unit_Population", [
        "Master list of units and the site that owns each one. Upload it whenever units arrive, leave or move site.",
        "Every upload becomes a version with an 'effective from' date chosen in the app; older months keep the "
        "population that was valid then.", "",
        "One row per unit. Equipment (unit ID) must be unique; spaces are removed on import.",
        "Units without a Site stay UNMAPPED until an Admin maps them. Extra columns are ignored.",
        f"Name the file {DATASET}_YYYY-MM-DD.xlsx (the effective date)."], sheets=(POPULATION,))
    lists = dataprod._lists(wb, sites)
    rows = dataprod._unit_rows(units) if units is not None and len(units) else None
    ws = dataprod._sheet(wb, POPULATION, rows, lists)
    ws.title = DATASET
    wb.move_sheet("Lists", offset=len(wb.sheetnames))
    dataprod._meta(wb, "unit_population", {"effective_from": effective.isoformat() if effective else ""})
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def effective_from_name(name: str) -> dt.date | None:
    """Unit_Population_2026-09-01.xlsx → 2026-09-01 (pre-fills the effective date)."""
    import re
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", name or "")
    try:
        return dt.date(*map(int, m.groups())) if m else None
    except ValueError:
        return None


def meta_effective(data: bytes) -> dt.date | None:
    raw = read_workbook(data)
    m = raw.get(META_SHEET)
    if m is None or m.shape[1] < 2:
        return None
    kv = dict(zip(m.iloc[:, 0].astype(str), m.iloc[:, 1].astype(str), strict=True))
    try:
        return dt.date.fromisoformat(kv.get("effective_from", ""))
    except ValueError:
        return None
