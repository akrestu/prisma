"""Hourly production (flash data, no approval): shift slots, the current production hour, master data from the
'Link Muatan' sheet, the per-shift Excel template, and turning input rows into volumes. No Streamlit or database.

A shift sheet has one line per hauler (with its loader and both operators) and trips per hour (12 slots). Volume = trips × load
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
# the order follows the work: excavator and its operator, material, then each truck it loads
# the order follows the work: excavator and its operator, material, then each truck it loads. Only what the data
# officer knows goes in the file; the hauler model and load come from the unit population on upload.
INPUT_COLS = ["Loader", "Operator", "Material", "Hauler ID", "Hauler operator", "PIT", "Disposal", "Distance (m)"]
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


def nrp_of(v) -> str | None:
    """'12345 - Budi S.' (drop-down label) or '12345' → '12345'."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or (not isinstance(v, str) and pd.isna(v)):
        return None
    s = str(v).strip()
    if not s:
        return None
    s = s.split(" - ", 1)[0].strip()
    return s[:-2] if s.endswith(".0") and s[:-2].isdigit() else s


def resolve(rows: pd.DataFrame, load: pd.DataFrame, targets: pd.DataFrame, units: pd.DataFrame | None = None,
            operators: pd.DataFrame | None = None) -> Resolved:
    """Fill hauler model, load, material group, loader model, hourly target and operator names; check every line.

    rows: loader, loader_nrp, hauler, hauler_nrp, material, pit, disposal, distance_m, r1..r12, remark_code, remark
    (legacy lines without a hauler ID may give hauler_model instead). One line = one hauler for one loader; the
    same hauler may appear on several lines when its operator changes during the shift."""
    out = rows.copy()
    for c in R:
        out[c] = num(out[c]) if c in out else np.nan
    for c in ("loader", "hauler"):
        out[c] = _ids(out[c]) if c in out else pd.NA
    for c in ("material", "hauler_model", "operator", "hauler_operator", "pit", "disposal", "remark", "remark_code"):
        out[c] = text(out[c].astype("string")) if c in out else pd.NA
    for c in ("loader_nrp", "hauler_nrp"):
        out[c] = out[c].map(nrp_of) if c in out else None
    out["distance_m"] = num(out["distance_m"]) if "distance_m" in out else np.nan
    has_trips = out[R].fillna(0).sum(axis=1) > 0
    legacy = (out["hauler_model"].notna() & out["loader"].notna()) if "hauler_model" in out else False
    truck = out["hauler"].notna() | legacy
    # pre-filled lines left without a truck and without trips are unused, not mistakes
    out = out[truck | has_trips].reset_index(drop=True)
    problems, warnings = [], []

    out["hauler_model"] = out["hauler_model"].mask(out["hauler_model"] == "?")   # Excel lookup found nothing
    models = dict(zip(units["unit_id"], units["model"], strict=True)) if units is not None and len(units) else {}
    out["hauler_model"] = out["hauler"].map(models).fillna(out["hauler_model"]) if len(out) else out["hauler_model"]
    lf = {(str(a).upper(), str(b).upper()): (v, g) for a, b, v, g in
          load[["material", "hauler_model", "muatan", "material_group"]].itertuples(index=False)}
    out["muatan"] = np.nan
    out["material_group"] = material_group(out["material"]).to_numpy()
    for i, r in out.iterrows():
        who = next((str(v) for v in (r["hauler"], r["hauler_model"]) if pd.notna(v)), "no hauler")
        line = f"Line {i + 1} ({r['loader'] if pd.notna(r['loader']) else 'no loader'} · {who})"
        if pd.isna(r["loader"]):
            problems.append(f"{line}: loader is empty.")
        if pd.isna(r["hauler"]) and pd.isna(r["hauler_model"]):
            problems.append(f"{line}: hauler is empty.")
            continue
        if pd.isna(r["hauler_model"]):
            problems.append(f"{line}: hauler {r['hauler']} is not in the unit population, so its model and load "
                            "are unknown (Data → Unit population).")
            continue
        if pd.isna(r["material"]):
            problems.append(f"{line}: material is empty.")
            continue
        hit = lf.get((str(r["material"]).upper(), str(r["hauler_model"]).upper()))
        if hit is None:
            problems.append(f"{line}: no load factor for {r['material']} × {r['hauler_model']} "
                            "(add it in Hourly setup).")
            continue
        out.loc[i, ["muatan", "material_group"]] = list(hit)
        bad = out.loc[i, R][(out.loc[i, R] < 0) | (out.loc[i, R] > 20)].dropna()
        if len(bad):
            problems.append(f"{line}: trips of one hauler in one hour must be between 0 and 20.")

    tg = {(u, g): (t, mdl) for u, mdl, g, t in
          targets[["unit_id", "model", "material_group", "target_per_hour"]].itertuples(index=False)} \
        if len(targets) else {}
    keys = list(zip(out["loader"], out["material_group"], strict=True))
    out["target_per_hour"] = [tg.get(k, (np.nan, None))[0] for k in keys]
    out["loader_model"] = [tg.get(k, (None, None))[1] for k in keys]
    if models:
        out["loader_model"] = out["loader_model"].fillna(out["loader"].map(models))
        unknown = sorted(set(out["loader"].dropna()) - set(models))
        if unknown:
            warnings.append(f"Loader not in the unit population: {', '.join(unknown)}.")
    no_target = sorted(set(out.loc[out["target_per_hour"].isna(), "loader"].dropna()))
    if no_target:
        warnings.append(f"No hourly target set for: {', '.join(no_target)} (Hourly setup).")

    names = dict(zip(operators["nrp"], operators["name"], strict=True)) if operators is not None and len(operators) \
        else {}
    out["operator"] = out["loader_nrp"].map(names).fillna(out["operator"]) if names else out["operator"]
    out["hauler_operator"] = out["hauler_nrp"].map(names).fillna(out["hauler_operator"]) if names \
        else out["hauler_operator"]
    if names:
        unknown = sorted({x for x in (*out["loader_nrp"], *out["hauler_nrp"]) if isinstance(x, str) and x not in names})
        if unknown:
            warnings.append(f"NRP not in the operator master: {', '.join(unknown)} (Admin → Operators).")
    missing = out[(out[R].fillna(0).sum(axis=1) > 0) & (out["hauler_nrp"].isna()) & out["hauler"].notna()]
    if len(missing):
        warnings.append(f"{len(missing)} line(s) with trips but no hauler operator: operator KPIs will miss them.")
    busy = out.melt(id_vars=["hauler"], value_vars=R).dropna()
    busy = busy[(busy["value"] > 0) & busy["hauler"].notna()]
    dup = busy[busy.duplicated(["hauler", "variable"], keep=False)]
    if len(dup):
        warnings.append("Same hauler on more than one line in the same hour: "
                        f"{', '.join(sorted(set(dup['hauler'])))} (fine when it changed loader or operator).")
    out["line"] = range(1, len(out) + 1)
    return Resolved(out, problems, warnings)


def to_long(rows: pd.DataFrame) -> pd.DataFrame:
    """Rows (with shift, date, site) → one record per line × hour: hour_slot, slot, rit, volume."""
    if rows.empty:
        return pd.DataFrame(columns=["site", "date", "shift", "loader", "hauler", "material_group", "hour_slot",
                                     "slot", "rit", "volume", "distance_m", "hauler_model", "operator",
                                     "hauler_operator", "loader_nrp", "hauler_nrp", "muatan", "target_per_hour"])
    keep = [c for c in rows.columns if c not in R]
    long = rows.melt(id_vars=keep, value_vars=R, var_name="rc", value_name="rit")
    long["slot"] = long["rc"].str[1:].astype(int)
    long["hour_slot"] = [SLOTS[s][k - 1] for s, k in zip(long["shift"], long["slot"], strict=True)]
    long["rit"] = long["rit"].fillna(0.0)
    long["volume"] = long["rit"] * long["muatan"]
    return long.drop(columns="rc")


# ------------------------------------------------------------------ Excel template (one shift per file)
def _label(nrp, names: dict) -> str | None:
    nrp = nrp_of(nrp)
    return None if not nrp else (f"{nrp} - {names[nrp]}" if nrp in names else nrp)


def build_template(site: str, date: dt.date, shift: str, load: pd.DataFrame, targets: pd.DataFrame,
                   lines: pd.DataFrame | None = None, coordinator: str = "", units: pd.DataFrame | None = None,
                   operators: pd.DataFrame | None = None) -> bytes:
    """Per-shift input workbook, one row per hauler. `lines` pre-fills loader, hauler and operators (e.g. from the
    previous shift) so the data officer only types trips. Drop-downs list the site's loaders, haulers, operators."""
    from openpyxl.utils import get_column_letter

    from core import dataprod
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws["A1"] = f"PRISMA · Hourly production · {shift} · one row per hauler"
    ws["A1"].font = Font(bold=True, size=14)
    for r, (k, v) in enumerate([("Site", site), ("Date", date), ("Shift", shift), ("Coordinator", coordinator)],
                               start=2):
        ws.cell(r, 1, k).font = Font(bold=True)
        ws.cell(r, 2, v)
    ws["B3"].number_format = "yyyy-mm-dd"
    for r, tip in enumerate(["How to fill: one row per truck. Pick Loader, Operator, Material and Hauler ID from the "
                             "drop-downs, then type the trips per hour.",
                             "Truck model and load are added automatically. Rows without a Hauler ID and without "
                             "trips are ignored.",
                             "Operator changed during the shift? Add a second row for the same truck."], start=2):
        ws.cell(r, 4, tip).font = Font(italic=True, color="55595F")
    heads = INPUT_COLS + SLOTS[shift] + TAIL_COLS
    widths = {"Loader": 11, "Hauler ID": 11, "Operator": 24, "Hauler operator": 24, "Material": 18, "Remark": 28}
    for j, h in enumerate(heads, start=1):
        c = ws.cell(HEADER_ROW, j, h)
        c.fill, c.font = dataprod.HEAD_FILL, dataprod.HEAD_FONT
        ws.column_dimensions[c.column_letter].width = 7 if h in SLOTS[shift] else widths.get(h, 14)
    names = dict(zip(operators["nrp"], operators["name"], strict=True)) if operators is not None and len(operators) \
        else {}
    u = units if units is not None else pd.DataFrame(columns=["unit_id", "type", "site"])
    u = u[u["site"] == site] if len(u) else u
    hu = u[u["type"].fillna("").str.contains("Haul", case=False)].sort_values("unit_id") if len(u) else u
    haulers = hu["unit_id"].tolist() if len(hu) else []
    loaders = sorted(set(targets["unit_id"]) if len(targets) else set())
    lists = wb.create_sheet("Lists")
    columns = {"A": sorted(load["material"].unique()) if len(load) else [],
               "B": [f"{k} - {v}" for k, v in REMARKS.items()], "C": loaders, "D": haulers,
               "E": [f"{n} - {nm}" for n, nm in sorted(names.items(), key=lambda x: x[1])]}
    for col, vals in columns.items():
        for i, v in enumerate(vals, start=1):
            lists[f"{col}{i}"] = v
    lists.sheet_state = "hidden"
    last = HEADER_ROW + 400
    pos = {h: get_column_letter(j) for j, h in enumerate(heads, start=1)}
    for head, src in (("Material", "A"), ("Remark code", "B"), ("Loader", "C"), ("Hauler ID", "D"),
                      ("Operator", "E"), ("Hauler operator", "E")):
        n = len(columns[src])
        if n:
            dv = DataValidation(type="list", formula1=f"=Lists!${src}$1:${src}${n}", allow_blank=True,
                                errorStyle="warning")
            dv.add(f"{pos[head]}{HEADER_ROW + 1}:{pos[head]}{last}")
            ws.add_data_validation(dv)
    first, lastc = pos[SLOTS[shift][0]], pos[SLOTS[shift][-1]]
    dv = DataValidation(type="whole", operator="between", formula1="0", formula2="20", allow_blank=True)
    dv.error, dv.errorTitle = "Trips of one hauler per hour: whole number 0–20", "Trips"
    dv.add(f"{first}{HEADER_ROW + 1}:{lastc}{last}")
    ws.add_data_validation(dv)
    recs = lines.to_dict("records") if lines is not None else []
    for i, r in enumerate(recs, start=HEADER_ROW + 1):
        name = r.get("operator") if isinstance(r.get("operator"), str) else None
        vals = {"Loader": r.get("loader"), "Operator": _label(r.get("loader_nrp"), names) or name,
                "Material": r.get("material"), "Hauler ID": r.get("hauler"),
                "Hauler operator": _label(r.get("hauler_nrp"), names), "PIT": r.get("pit"),
                "Disposal": r.get("disposal"), "Distance (m)": r.get("distance_m")}
        for h, v in vals.items():
            ws[f"{pos[h]}{i}"] = None if v is None or (isinstance(v, float) and pd.isna(v)) else v
    ws.freeze_panes = ws.cell(HEADER_ROW + 1, 5)          # loader, operator, material and truck stay visible
    dataprod._meta(wb, "hourly", {"site": site, "date": date.isoformat(), "shift": shift, "layout": "per_hauler"})
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
                              f"(the hour columns follow the shift in B4). Download the current template."])
    body = x.iloc[HEADER_ROW:, :len(expected)].copy()
    body.columns = ["loader", "loader_nrp", "material", "hauler", "hauler_nrp", "pit", "disposal", "distance_m",
                    *R, "remark_code", "remark"]
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
        out.append({"loader": loader, "operator": operator, "loader_nrp": None, "hauler": None, "hauler_nrp": None,
                    "material": mat.strip(),
                    "hauler_model": str(r.iloc[7]).strip() if pd.notna(r.iloc[7]) else None,
                    "pit": None, "disposal": None, "distance_m": None,
                    **{f"r{k}": trips[k - 1] for k in range(1, 13)}, "remark_code": None, "remark": None})
    return pd.DataFrame(out, columns=["loader", "operator", "loader_nrp", "hauler", "hauler_nrp", "material",
                                      "hauler_model", "pit", "disposal", "distance_m", *R, "remark_code", "remark"])
