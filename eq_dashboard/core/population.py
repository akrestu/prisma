"""Unit Population workbook: master list of units and their site, versioned by an effective date. No database here.

One sheet with the same columns as the 'Unit Population' sheet of older Production Data files. A version applies from its
effective date until the next version; a Production Data month uses the newest version effective on or before the
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
from core.validate import META_SHEET, POPULATION, UNIT_POPULATION, StructureError, file_stem

DATASET = UNIT_POPULATION
SHEET = POPULATION.name                                  # "Unit Population"
SHEET_NAMES = (SHEET, "Unit_Population", "Populasi Unit")   # current name first; older names are still read
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
        raise StructureError([f"Sheet '{SHEET}' was not found (the old names 'Unit_Population' and 'Populasi Unit' "
                              "also work)."])
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


def restrict(old: pd.DataFrame | None, new: pd.DataFrame, allowed: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keep only the changes a user may make: units whose current site and new site are both in `allowed`
    (added units: new site allowed; removed units: current site allowed). Every other unit stays as it is in `old`.
    Returns (population to save, ignored changes [change, unit_id, site])."""
    if old is None or old.empty:
        keep = new[new["site"].isin(allowed)]
        ignored = new[~new["site"].isin(allowed)].assign(change="added in another site")
        return keep[COLS].reset_index(drop=True), ignored[["change", "unit_id", "site"]].reset_index(drop=True)
    o, n = old.set_index("unit_id")[COLS[1:]], new.set_index("unit_id")[COLS[1:]]
    ok = set(allowed)
    out, ignored = [], []
    for u in sorted(set(o.index) | set(n.index)):
        before = o.loc[u] if u in o.index else None
        after = n.loc[u] if u in n.index else None
        mine = all(r is None or r["site"] in ok for r in (before, after))
        if mine:
            if after is not None:
                out.append((u, *after.tolist()))
            continue
        if before is not None:                      # not this user's to change: keep the version in force
            out.append((u, *before.tolist()))
        same = before is not None and after is not None and before.astype(str).equals(after.astype(str))
        if not same:
            what = ("added" if before is None else "removed" if after is None else
                    f"moved to {after['site']}" if before["site"] != after["site"] else "changed")
            ignored.append((what, u, (after if after is not None else before)["site"]))
    return (pd.DataFrame(out, columns=COLS), pd.DataFrame(ignored, columns=["change", "unit_id", "site"]))


def movements(units: pd.DataFrame, versions: pd.DataFrame) -> pd.DataFrame:
    """History of every unit across versions: arrived, left, or moved site, with the date it applies from.

    `units`: unit_id, site, type, model, version_id (all versions). `versions`: id, effective_from. Versions are
    replayed in effective order; of two versions on the same date the newer upload wins (as for population_for).
    The first version is the starting point, so it produces no rows."""
    cols = ["date", "unit_id", "change", "from_site", "to_site", "type", "model", "version_id"]
    if versions.empty or units.empty:
        return pd.DataFrame(columns=cols)
    order = (versions.sort_values(["effective_from", "id"]).drop_duplicates("effective_from", keep="last"))
    rows, prev = [], None
    for v in order.itertuples():
        cur = units[units["version_id"] == v.id].drop_duplicates("unit_id").set_index("unit_id")
        if prev is not None:
            both = cur.index.intersection(prev.index)
            moved = both[(cur.loc[both, "site"] != prev.loc[both, "site"]).to_numpy()]
            rows += [(v.effective_from, u, "arrived", None, cur.loc[u, "site"], cur.loc[u, "type"], cur.loc[u, "model"],
                      v.id) for u in cur.index.difference(prev.index)]
            rows += [(v.effective_from, u, "left", prev.loc[u, "site"], None, prev.loc[u, "type"], prev.loc[u, "model"],
                      v.id) for u in prev.index.difference(cur.index)]
            rows += [(v.effective_from, u, "moved", prev.loc[u, "site"], cur.loc[u, "site"], cur.loc[u, "type"],
                      cur.loc[u, "model"], v.id) for u in moved]
        prev = cur
    out = pd.DataFrame(rows, columns=cols)
    for c in ("from_site", "to_site"):
        out[c] = out[c].astype(object).where(out[c].notna(), None)
    return out.sort_values(["date", "unit_id"], ascending=[False, True]).reset_index(drop=True)


def site_since(moves: pd.DataFrame, current: pd.DataFrame, first: dt.date | None) -> pd.Series:
    """Per current unit: the date its present site applies from (last move or arrival, else the first version)."""
    last = (moves[moves["change"].isin(["moved", "arrived"])].sort_values("date")
            .drop_duplicates("unit_id", keep="last").set_index("unit_id")["date"])
    return current["unit_id"].map(last).fillna(first) if first else current["unit_id"].map(last)


def build_template(sites: list[str], units: pd.DataFrame | None = None, effective: dt.date | None = None) -> bytes:
    """Unit Population workbook in the template style (README, yellow headers with notes, Site drop-down)."""
    from core import dataprod  # shares the styling helpers
    wb = Workbook()
    dataprod._readme(wb, f"PRISMA · {DATASET}", [
        "Master list of units and the site that owns each one. Upload it only when units change: a unit arrives, "
        "leaves, moves site or changes type/model.",
        "Every upload becomes a version with an 'effective from' date chosen in the app; older months keep the "
        "population that was valid then.", "",
        "One row per unit. Equipment (unit ID) must be unique; spaces are removed on import.",
        "Units without a Site stay UNMAPPED until an Admin maps them. Extra columns are ignored.",
        f"Name the file {file_name(dt.date(2026, 9, 1))} (the effective date).",
        "Upload it in PRISMA → Input & upload → Unit Population."], sheets=(POPULATION,))
    lists = dataprod._lists(wb, sites)
    rows = dataprod._unit_rows(units) if units is not None and len(units) else None
    dataprod._sheet(wb, POPULATION, rows, lists)
    wb.move_sheet("Lists", offset=len(wb.sheetnames))
    dataprod._meta(wb, "unit_population", {"dataset": DATASET, "effective_from": effective.isoformat() if effective else ""})
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def file_name(effective: dt.date) -> str:
    """Unit_Population_2026-09-01.xlsx"""
    return f"{file_stem(DATASET)}_{effective:%Y-%m-%d}.xlsx"


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
