"""Hourly production (flash data, no approval): shift slots, the current production hour, master data from the
'Link Muatan' sheet, the per-shift Excel template, and turning input rows into volumes. No Streamlit or database.

A shift sheet has one line per excavator × hauler model with trips per hour (12 slots). Volume = trips × load
factor (material × hauler model): BCM for OB, ton for coal. Hourly figures are an estimate for monitoring; the
official monthly numbers stay those of the approved Data_Prod.
"""
from __future__ import annotations

import datetime as dt
import io
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation

from core.clean import _ids, material_group
from core.io import excel_date, num, read_workbook, text
from core.validate import HOUR_SLOTS, StructureError

SHIFTS = ("DS", "NS")
SLOTS = {"DS": HOUR_SLOTS[:12], "NS": HOUR_SLOTS[12:]}      # DS 06-07 … 17-18, NS 18-19 … 05-06
R = [f"r{i}" for i in range(1, 13)]                          # storage columns for the 12 slots
SHEET = "Hourly"
HEADER_ROW = 7                                               # Excel row of the table header in the template
INPUT_COLS = ["Loader", "Operator", "Material", "Hauler model", "PIT", "Disposal", "Distance (m)"]
TAIL_COLS = ["Remark code", "Remark"]
REMARKS = {  # common reasons on the site boards; any 3-digit Eq.Event reason code is also accepted
    "100": "Productivity achieved", "101": "Change shift", "301": "Standby / waiting", "302": "Rain",
    "303": "Slippery road", "304": "Blasting", "305": "Waiting hauler", "401": "Breakdown loader",
    "402": "Breakdown hauler", "501": "Scheduled maintenance", "502": "Digging method / front condition",
}


# ------------------------------------------------------------------ time
def production_hour(now: dt.datetime) -> tuple[dt.date, str, int]:
    """(production date, shift, slot 1..12) for a WIB time. The production day starts at 06:00: the night shift
    after midnight still belongs to the previous date."""
    h = now.hour
    if 6 <= h < 18:
        return now.date(), "DS", h - 6 + 1
    if h >= 18:
        return now.date(), "NS", h - 18 + 1
    return now.date() - dt.timedelta(days=1), "NS", h + 6 + 1


def slot_label(shift: str, slot: int) -> str:
    return SLOTS[shift][slot - 1]


# ------------------------------------------------------------------ master data from 'Link Muatan'
def parse_link_muatan(data: bytes) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(load factors [material, material_group, hauler_model, muatan], targets [unit_id, model, target_per_hour])
    from the 'Link Muatan' sheet of the Mst Hourly workbook."""
    raw = read_workbook(data)
    if "Link Muatan" not in raw:
        raise StructureError(["Sheet 'Link Muatan' was not found."])
    x = raw["Link Muatan"]
    hdr = x.iloc[0]
    if str(hdr.iloc[1]).strip() != "Material":
        raise StructureError(["'Link Muatan': cell B1 must be 'Material' with hauler models to its right."])
    models = {j: str(hdr.iloc[j]).strip() for j in range(2, len(hdr)) if pd.notna(hdr.iloc[j])
              and str(hdr.iloc[j]).strip() and str(hdr.iloc[j]).strip() != "Tanggal"}
    models = {j: v for j, v in models.items() if j < 9}      # matrix block B:I; the unit list starts at K
    lf = []
    for i in range(1, len(x)):
        mat = x.iloc[i, 1]
        if pd.isna(mat) or not str(mat).strip():
            break
        mat = str(mat).strip()
        for j, model in models.items():
            v = pd.to_numeric(x.iloc[i, j], errors="coerce")
            if pd.notna(v) and v > 0:
                lf.append((mat, model, float(v)))
    lf = pd.DataFrame(lf, columns=["material", "hauler_model", "muatan"])
    lf.insert(1, "material_group", material_group(lf["material"]).to_numpy())
    tg = x.iloc[1:, 10:13].copy()
    tg.columns = ["unit_id", "model", "target_per_hour"]
    tg["unit_id"] = _ids(tg["unit_id"])
    tg["target_per_hour"] = num(tg["target_per_hour"])
    tg = tg.dropna(subset=["unit_id", "target_per_hour"])
    tg = tg[tg["unit_id"].str.match(r"^[A-Z]{2,4}\d", na=False)].drop_duplicates("unit_id")
    return lf.reset_index(drop=True), tg.reset_index(drop=True)


# ------------------------------------------------------------------ resolving input rows
@dataclass
class Resolved:
    rows: pd.DataFrame
    problems: list[str] = field(default_factory=list)     # blocking
    warnings: list[str] = field(default_factory=list)


def resolve(rows: pd.DataFrame, load: pd.DataFrame, targets: pd.DataFrame,
            units: pd.DataFrame | None = None) -> Resolved:
    """Fill muatan, material group, loader model and hourly target; check every line.

    rows: loader, operator, material, hauler_model, pit, disposal, distance_m, r1..r12, remark_code, remark."""
    out = rows.copy()
    for c in R:
        out[c] = num(out[c]) if c in out else np.nan
    out["loader"] = _ids(out["loader"])
    for c in ("material", "hauler_model", "operator", "pit", "disposal", "remark", "remark_code"):
        out[c] = text(out[c]) if c in out else pd.NA
    out["distance_m"] = num(out["distance_m"]) if "distance_m" in out else np.nan
    has_trips = out[R].fillna(0).sum(axis=1) > 0
    out = out[out["loader"].notna() | has_trips].reset_index(drop=True)
    problems, warnings = [], []
    lf = {(str(a).upper(), str(b).upper()): (v, g) for a, b, v, g in
          load[["material", "hauler_model", "muatan", "material_group"]].itertuples(index=False)}
    out["muatan"] = np.nan
    out["material_group"] = material_group(out["material"]).to_numpy()
    for i, r in out.iterrows():
        line = f"Line {i + 1} ({r['loader'] or 'no loader'})"
        if pd.isna(r["loader"]):
            problems.append(f"{line}: loader is empty.")
        if pd.isna(r["material"]) or pd.isna(r["hauler_model"]):
            problems.append(f"{line}: material and hauler model are required.")
            continue
        hit = lf.get((str(r["material"]).upper(), str(r["hauler_model"]).upper()))
        if hit is None:
            problems.append(f"{line}: no load factor for {r['material']} × {r['hauler_model']} "
                            "(add it in Hourly setup).")
            continue
        out.loc[i, ["muatan", "material_group"]] = list(hit)
        bad = out.loc[i, R][(out.loc[i, R] < 0) | (out.loc[i, R] > 60)].dropna()
        if len(bad):
            problems.append(f"{line}: trips per hour must be between 0 and 60.")
    tg = {(u, g): (t, mdl) for u, mdl, g, t in
          targets[["unit_id", "model", "material_group", "target_per_hour"]].itertuples(index=False)} \
        if len(targets) else {}
    out["target_per_hour"] = [tg.get((u, g), (np.nan, None))[0] for u, g in zip(out["loader"], out["material_group"],
                                                                                strict=True)]
    out["loader_model"] = [tg.get((u, g), (None, None))[1] for u, g in zip(out["loader"], out["material_group"],
                                                                          strict=True)]
    if units is not None and len(units):
        known = dict(zip(units["unit_id"], units["model"], strict=True))
        out["loader_model"] = out["loader_model"].fillna(out["loader"].map(known))
        unknown = sorted(set(out["loader"].dropna()) - set(known))
        if unknown:
            warnings.append(f"Not in the unit population: {', '.join(unknown)}.")
    no_target = sorted(set(out.loc[out["target_per_hour"].isna(), "loader"].dropna()))
    if no_target:
        warnings.append(f"No hourly target set for: {', '.join(no_target)} (Hourly setup).")
    out["line"] = range(1, len(out) + 1)
    return Resolved(out, problems, warnings)


def to_long(rows: pd.DataFrame) -> pd.DataFrame:
    """Rows (with shift, date, site) → one record per line × hour: hour_slot, slot, rit, volume."""
    if rows.empty:
        return pd.DataFrame(columns=["site", "date", "shift", "loader", "material_group", "hour_slot", "slot",
                                     "rit", "volume", "distance_m", "hauler_model"])
    keep = [c for c in rows.columns if c not in R]
    long = rows.melt(id_vars=keep, value_vars=R, var_name="rc", value_name="rit")
    long["slot"] = long["rc"].str[1:].astype(int)
    long["hour_slot"] = [SLOTS[s][k - 1] for s, k in zip(long["shift"], long["slot"], strict=True)]
    long["rit"] = long["rit"].fillna(0.0)
    long["volume"] = long["rit"] * long["muatan"]
    return long.drop(columns="rc")


# ------------------------------------------------------------------ Excel template (one shift per file)
def build_template(site: str, date: dt.date, shift: str, load: pd.DataFrame, targets: pd.DataFrame,
                   lines: pd.DataFrame | None = None, coordinator: str = "") -> bytes:
    """Per-shift input workbook. `lines` (loader, operator, material, hauler_model, pit, disposal, distance_m)
    pre-fills the rows, e.g. from the previous shift, so the operator only types trips."""
    from core import dataprod
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws["A1"] = f"PRISMA · Hourly production · {shift}"
    ws["A1"].font = Font(bold=True, size=14)
    for r, (k, v) in enumerate([("Site", site), ("Date", date), ("Shift", shift), ("Coordinator", coordinator)],
                               start=2):
        ws.cell(r, 1, k).font = Font(bold=True)
        ws.cell(r, 2, v)
    ws["B3"].number_format = "yyyy-mm-dd"
    heads = INPUT_COLS + SLOTS[shift] + TAIL_COLS
    for j, h in enumerate(heads, start=1):
        c = ws.cell(HEADER_ROW, j, h)
        c.fill, c.font = dataprod.HEAD_FILL, dataprod.HEAD_FONT
        ws.column_dimensions[c.column_letter].width = 7 if h in SLOTS[shift] else (26 if h == "Remark" else 14)
    lists = wb.create_sheet("Lists")
    mats = sorted(load["material"].unique()) if len(load) else []
    models = sorted(load["hauler_model"].unique()) if len(load) else []
    for col, vals in (("A", mats), ("B", models), ("C", [f"{k} - {v}" for k, v in REMARKS.items()]),
                      ("D", sorted(targets["unit_id"]) if len(targets) else [])):
        for i, v in enumerate(vals, start=1):
            lists[f"{col}{i}"] = v
    lists.sheet_state = "hidden"
    last = HEADER_ROW + 300
    for letter, src, n in (("C", "A", len(mats)), ("D", "B", len(models)), ("A", "D", len(targets))):
        if n:
            dv = DataValidation(type="list", formula1=f"=Lists!${src}$1:${src}${n}", allow_blank=True,
                                errorStyle="warning")
            dv.add(f"{letter}{HEADER_ROW + 1}:{letter}{last}")
            ws.add_data_validation(dv)
    first_slot = len(INPUT_COLS) + 1
    from openpyxl.utils import get_column_letter
    rng = f"{get_column_letter(first_slot)}{HEADER_ROW + 1}:{get_column_letter(first_slot + 11)}{last}"
    dv = DataValidation(type="whole", operator="between", formula1="0", formula2="60", allow_blank=True)
    dv.error, dv.errorTitle = "Trips per hour: whole number 0–60", "Trips"
    dv.add(rng)
    ws.add_data_validation(dv)
    code_col = get_column_letter(first_slot + 12)
    dv = DataValidation(type="list", formula1="=Lists!$C$1:$C$" + str(len(REMARKS)), allow_blank=True,
                        errorStyle="warning")
    dv.add(f"{code_col}{HEADER_ROW + 1}:{code_col}{last}")
    ws.add_data_validation(dv)
    if lines is not None:
        for i, r in enumerate(lines.itertuples(index=False), start=HEADER_ROW + 1):
            for j, v in enumerate([r.loader, r.operator, r.material, r.hauler_model, r.pit, r.disposal,
                                   r.distance_m], start=1):
                ws.cell(i, j, None if v is None or (isinstance(v, float) and pd.isna(v)) else v)
    ws.freeze_panes = ws.cell(HEADER_ROW + 1, 2)
    dataprod._meta(wb, "hourly", {"site": site, "date": date.isoformat(), "shift": shift})
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@dataclass
class HourlyFile:
    site: str
    date: dt.date
    shift: str
    coordinator: str
    rows: pd.DataFrame


def parse_template(data: bytes) -> HourlyFile:
    raw = read_workbook(data)
    if SHEET not in raw:
        raise StructureError([f"Sheet '{SHEET}' was not found: use the Hourly production template."])
    x = raw[SHEET]
    head = {str(x.iloc[i, 0]).strip(): x.iloc[i, 1] for i in range(1, 5) if i < len(x) and pd.notna(x.iloc[i, 0])}
    problems = []
    site = str(head.get("Site") or "").strip()
    shift = str(head.get("Shift") or "").strip().upper()
    date = excel_date(pd.Series([head.get("Date")])).iloc[0]
    if not site:
        problems.append("Cell B2 (Site) is empty.")
    if shift not in SHIFTS:
        problems.append("Cell B4 (Shift) must be DS or NS.")
    if pd.isna(date):
        problems.append("Cell B3 (Date) must be a date.")
    if problems:
        raise StructureError(problems)
    hdr = [str(v).strip() if pd.notna(v) else "" for v in x.iloc[HEADER_ROW - 1]]
    expected = INPUT_COLS + SLOTS[shift] + TAIL_COLS
    if hdr[:len(expected)] != expected:
        raise StructureError([f"Row {HEADER_ROW} must hold the headers: {', '.join(expected)} "
                              f"(the hour columns follow the shift in B4)."])
    body = x.iloc[HEADER_ROW:, :len(expected)].copy()
    body.columns = ["loader", "operator", "material", "hauler_model", "pit", "disposal", "distance_m", *R,
                    "remark_code", "remark"]
    body = body.dropna(how="all")
    body["remark_code"] = text(body["remark_code"].astype("string")).str.extract(r"^(\d{3})", expand=False)
    return HourlyFile(site, date.date(), shift, str(head.get("Coordinator") or "").strip(),
                      body.reset_index(drop=True))


# ------------------------------------------------------------------ legacy 'Mst Hourly' shift sheets
def parse_mst_shift(sheet: pd.DataFrame) -> pd.DataFrame:
    """Rows from a DS/NS sheet of the old Mst Hourly workbook (blocks 'Ritasi OB' and 'Ritasi CG').

    Columns used: D excavator, F operator, G material, H hauler model, M..X trips per hour. Lines without a
    material are template filler and are skipped."""
    out = []
    loader, operator = None, None
    for i in range(len(sheet)):
        r = sheet.iloc[i]
        exca = r.iloc[3] if len(r) > 3 else None
        mat = r.iloc[6] if len(r) > 6 else None
        if isinstance(exca, str) and exca.strip() not in ("", "Exca", "0", loader):
            loader, operator = exca.strip(), None
        if isinstance(r.iloc[5], str) and r.iloc[5].strip() and r.iloc[5].strip() != "Operator":
            operator = r.iloc[5].strip()
        if not (isinstance(mat, str) and mat.strip()[:2].upper() in ("OB", "CG")) or loader is None:
            continue
        trips = [pd.to_numeric(v, errors="coerce") for v in r.iloc[12:24].tolist()]
        out.append({"loader": loader, "operator": operator, "material": mat.strip(),
                    "hauler_model": str(r.iloc[7]).strip() if pd.notna(r.iloc[7]) else None,
                    "pit": None, "disposal": None, "distance_m": None,
                    **{f"r{k}": trips[k - 1] for k in range(1, 13)}, "remark_code": None, "remark": None})
    return pd.DataFrame(out, columns=["loader", "operator", "material", "hauler_model", "pit", "disposal",
                                      "distance_m", *R, "remark_code", "remark"])
