"""Hourly Production export: everything entered for some sites and dates in one workbook, for a manual review.

Sheets: Shifts (one row per shift with status and totals), Lines (each line as entered, trips per hour H1-H12),
Per hour (one row per line × hour with trips) and Remarks (hour remarks). Not an upload template: to correct a
shift, use the shift's own Excel template on the Input hourly production page.
"""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import hourly as H
from db import models as m
from db.repo import HOURLY_REMARK_COLS, frame, hourly_range

SHIFT_COLS = {"site": "Site", "date": "Date", "shift": "Shift", "coordinator": "Coordinator", "status": "Status",
              "source": "Entered via", "lines": "Lines", "trips": "Trips", "ob_bcm": "OB (BCM)", "cg_t": "Coal (t)",
              "updated_by": "Updated by", "updated_at": "Updated at", "submitted_by": "Submitted by",
              "submitted_at": "Submitted at", "reviewed_by": "Reviewed by", "reviewed_at": "Reviewed at",
              "review_note": "Review note"}
LINE_COLS = {"site": "Site", "date": "Date", "shift": "Shift", "line": "Line", "loader": "Loader",
             "loader_model": "Loader model", "operator": "Loader operator", "loader_nrp": "Loader NRP",
             "hauler": "Hauler", "hauler_model": "Hauler model", "hauler_operator": "Hauler operator",
             "hauler_nrp": "Hauler NRP", "material": "Material", "material_group": "Group", "pit": "Loading location",
             "disposal": "Disposal", "distance_m": "Horizontal (m)", "dist_v": "Vertical (m)",
             "muatan": "Load factor", "target_per_hour": "Target per hour", "target_source": "Target source",
             "remark_code": "Remark code", "remark": "Remark"}
# the same storage column is a different clock hour in DS and NS
HOUR_LABEL = {f"r{i}": f"H{i} ({H.SLOTS['DS'][i - 1]} | {H.SLOTS['NS'][i - 1]})" for i in range(1, 13)}
KEY = ["site", "date", "shift"]


def shifts(s: Session, sites: list[str], d0: dt.date, d1: dt.date) -> pd.DataFrame:
    h = m.HourlyShift
    return frame(s, select(h.site, h.date, h.shift, h.coordinator, h.status, h.source, h.updated_by, h.updated_at,
                           h.submitted_by, h.submitted_at, h.reviewed_by, h.reviewed_at, h.review_note)
                 .where(h.site.in_(sites), h.date >= d0, h.date <= d1).order_by(h.date, h.site, h.shift))


def remarks(s: Session, sites: list[str], d0: dt.date, d1: dt.date) -> pd.DataFrame:
    r, h = m.HourlyRemark, m.HourlyShift
    return frame(s, select(h.site, h.date, h.shift, *[getattr(r, c) for c in HOURLY_REMARK_COLS])
                 .join(h, h.id == r.shift_id)
                 .where(h.site.in_(sites), h.date >= d0, h.date <= d1).order_by(h.date, h.site, h.shift, r.slot))


def load(s: Session, sites: list[str], d0: dt.date, d1: dt.date) -> dict[str, pd.DataFrame]:
    return {"shifts": shifts(s, sites, d0, d1), "rows": hourly_range(s, sites, d0, d1),
            "remarks": remarks(s, sites, d0, d1)}


def _naive(df: pd.DataFrame) -> pd.DataFrame:
    """Excel has no time zones: timestamps in WIB without the zone."""
    out = df.copy()
    for c in out.columns:
        if isinstance(out[c].dtype, pd.DatetimeTZDtype):
            out[c] = out[c].dt.tz_convert("Asia/Jakarta").dt.tz_localize(None)
    return out


def frames(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """The four sheets with readable headers."""
    rows, sh, rem = data["rows"].copy(), data["shifts"].copy(), data["remarks"].copy()
    long = H.to_long(rows)
    if len(rows):
        rows[H.R] = rows[H.R].apply(pd.to_numeric, errors="coerce")
        rows["trips"] = rows[H.R].fillna(0).sum(axis=1)
        rows = rows.join(long.groupby(KEY + ["line"])["volume"].sum().rename("volume"), on=KEY + ["line"])

    # shift totals: lines, trips, OB BCM and coal t (a shift without lines keeps zeros)
    for c in ("lines", "trips", "ob_bcm", "cg_t"):
        sh[c] = 0.0
    if len(rows):
        tot = pd.DataFrame({"lines": rows.groupby(KEY).size(), "trips": rows.groupby(KEY)["trips"].sum(),
                            "ob_bcm": long[long["material_group"] == "OB"].groupby(KEY)["volume"].sum(),
                            "cg_t": long[long["material_group"] == "CG"].groupby(KEY)["volume"].sum()})
        got = sh[KEY].join(tot, on=KEY)
        for c in tot.columns:
            sh[c] = got[c].fillna(0).to_numpy()
    sh = sh.reindex(columns=list(SHIFT_COLS)).rename(columns=SHIFT_COLS)

    lines = rows.reindex(columns=[*LINE_COLS, *H.R, "trips", "volume"])
    if len(lines):
        lines = lines.sort_values(["date", "site", "shift", "line"], kind="stable")
    lines = lines.rename(columns={**LINE_COLS, **HOUR_LABEL, "trips": "Trips", "volume": "Volume (BCM / t)"})

    per = long[long["rit"] > 0]
    per = per.reindex(columns=["site", "date", "shift", "hour_slot", "slot", "line", "loader", "hauler", "material",
                               "material_group", "pit", "disposal", "rit", "volume"])
    if len(per):
        per = per.sort_values(["date", "site", "shift", "slot", "line"], kind="stable")
    per = per.drop(columns=["slot"]).rename(columns={
        "site": "Site", "date": "Date", "shift": "Shift", "hour_slot": "Hour", "line": "Line", "loader": "Loader",
        "hauler": "Hauler", "material": "Material", "material_group": "Group", "pit": "Loading location",
        "disposal": "Disposal", "rit": "Trips", "volume": "Volume (BCM / t)"})

    rem["hour"] = [H.SLOTS[sf][int(k) - 1] if pd.notna(k) and 1 <= int(k) <= 12 else None
                   for sf, k in zip(rem["shift"], rem["slot"], strict=True)] if len(rem) else None
    rem = (rem.reindex(columns=["site", "date", "shift", "hour", "loader", "hauler", "code", "remark"])
           .rename(columns={"site": "Site", "date": "Date", "shift": "Shift", "hour": "Hour", "loader": "Loader",
                            "hauler": "Hauler", "code": "Code", "remark": "Remark"}))
    return {"Shifts": _naive(sh), "Lines": _naive(lines), "Per hour": _naive(per), "Remarks": _naive(rem)}


def workbook(data: dict[str, pd.DataFrame], sites: list[str], d0: dt.date, d1: dt.date,
             now: dt.datetime | None = None) -> bytes:
    """One .xlsx: header row frozen, filters on, readable column widths, an About sheet saying what it holds."""
    from openpyxl.utils import get_column_letter

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        about = pd.DataFrame([["Hourly Production export (for review; not an upload template)", ""],
                              ["Sites", ", ".join(sites)], ["Dates", f"{d0:%d %b %Y} – {d1:%d %b %Y}"],
                              ["Exported", f"{(now or dt.datetime.now()):%d %b %Y %H:%M}"],
                              ["Lines", "H1-H12 = trips per hour: DS 06-07 … 17-18, NS 18-19 … 05-06"]])
        about.to_excel(xw, sheet_name="About", index=False, header=False)
        xw.sheets["About"].column_dimensions["A"].width = 22
        xw.sheets["About"].column_dimensions["B"].width = 70
        for name, df in frames(data).items():
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "A2"
            if ws.max_row > 1:
                ws.auto_filter.ref = ws.dimensions
            for i, col in enumerate(df.columns, start=1):
                letter = get_column_letter(i)
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(300)]) + 2
                ws.column_dimensions[letter].width = min(max(width, 8), 40)
                fmt = "dd mmm yyyy hh:mm" if str(col).endswith(" at") else "dd mmm yyyy" if col == "Date" else None
                if fmt:
                    for cell in ws[letter][1:]:
                        cell.number_format = fmt
    return buf.getvalue()


def file_name(sites: list[str], d0: dt.date, d1: dt.date) -> str:
    """Hourly_Review_WBK-BAU_20261101-20261130.xlsx (not Hourly_Production_…, the name of a shift template)."""
    who = "_".join(sites) if len(sites) <= 2 else f"{len(sites)}_sites"
    return f"Hourly_Review_{who}_{d0:%Y%m%d}-{d1:%Y%m%d}.xlsx"
