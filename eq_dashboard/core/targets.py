"""Availability & reliability targets per site × month (Production Data): the Targets workbook (download,
import) and the lookup (NULL = no target yet)."""
from __future__ import annotations

import io

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from db import models as m

COLUMN_MAP = {
    "Year": "year", "Month": "month", "Site": "site", "Target PA": "pa", "Target UoA": "uoa",
    "MTBS Target": "mtbs", "MTTR Target": "mttr", "Sched. Down Target": "sched_down",
    "PM Accuracy Target": "pm_accuracy", "SR Target": "sr", "Distance Target": "distance",
}
EXTRA = ["sr", "distance"]          # hourly screen targets, kept in the same table
PCT = ("pa", "uoa", "sched_down", "pm_accuracy")   # stored and written as fractions (0.85 = 85%)
FILE_STEM = "Production_Targets"
METRICS = ["pa", "uoa", "mtbs", "mttr", "sched_down", "pm_accuracy"]


def read_target_file(data: bytes) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(data))
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in ["Year", "Month"] if c not in df.columns]
    if missing:
        raise ValueError(f"Target.xlsx is missing columns: {', '.join(missing)}")
    df = df.rename(columns=COLUMN_MAP)
    df = df[[v for v in COLUMN_MAP.values() if v in df.columns]]
    df = df.dropna(subset=["year", "month"])
    df["year"], df["month"] = df["year"].astype(int), df["month"].astype(int)
    for c in (*METRICS, *EXTRA):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def import_targets(s: Session, data: bytes, sites: list[str] | None = None) -> int:
    """File dengan kolom Site dipakai apa adanya; tanpa Site diterapkan ke `sites` (default semua site aktif).
    Baris yang sudah ada (site, tahun, bulan) ditimpa."""
    df = read_target_file(data)
    if "site" not in df.columns or df["site"].isna().all():
        targets = sites or [x.code for x in s.scalars(select(m.Site).where(m.Site.active))]
        if not targets:
            raise ValueError("No sites yet. Import a Production Data workbook first or choose target sites.")
        df = pd.concat([df.assign(site=code) for code in targets], ignore_index=True)
    cols = [c for c in (*METRICS, *EXTRA) if c in df.columns]    # a column missing from the file is left as it is
    if not cols:
        raise ValueError("The file has no target columns (e.g. Target PA, Target UoA, MTBS Target).")
    part = df[["site", "year", "month", *cols]]
    recs = part.astype(object).where(part.notna(), None).to_dict("records")
    stmt = pg_insert(m.Target).values(recs)
    stmt = stmt.on_conflict_do_update(index_elements=["site", "year", "month"],
                                      set_={c: stmt.excluded[c] for c in cols})
    s.execute(stmt)
    return len(recs)


def target_for(s: Session, site: str, year: int, month: int) -> dict[str, float | None]:
    t = s.scalar(select(m.Target).where(m.Target.site == site, m.Target.year == year, m.Target.month == month))
    return {c: (getattr(t, c) if t else None) for c in METRICS}


def build_template(site: str, year: int, current: pd.DataFrame) -> bytes:
    """Targets workbook of one site and year (12 months, current values filled in): edit and import it back.
    `current`: month + the target columns as stored (percentages as fractions)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from core import dataprod
    head = {v: k for k, v in COLUMN_MAP.items()}
    cols = ["year", "month", "site", *METRICS, *EXTRA]
    grid = pd.DataFrame({"month": range(1, 13)}).merge(current, on="month", how="left").assign(year=year, site=site)
    wb = Workbook()
    ws = wb.active
    ws.title = "Targets"
    for j, c in enumerate(cols, start=1):
        cell = ws.cell(1, j, head[c])
        cell.fill, cell.font = dataprod.HEAD_FILL, dataprod.HEAD_FONT
        ws.column_dimensions[cell.column_letter].width = 16
    for i, r in enumerate(grid.reindex(columns=cols).itertuples(index=False), start=2):
        for j, (c, v) in enumerate(zip(cols, r, strict=True), start=1):
            cell = ws.cell(i, j, None if pd.isna(v) else v)
            if c in PCT:
                cell.number_format = "0.0%"
    note = ws.cell(1, len(cols) + 2, "Percent targets as percentages (85%), MTBS/MTTR in hours, SR in BCM per t, "
                                     "Distance in m. Empty cell = no target. Import: Production targets → "
                                     "Availability & reliability.")
    note.font = Font(italic=True, color="55595F")
    ws.freeze_panes = "A2"
    dataprod._meta(wb, "targets", {"dataset": "Production targets", "site": site, "year": str(year)})
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def file_name(site: str, year: int) -> str:
    """Production_Targets_WBK-BAU_2026.xlsx"""
    return f"{FILE_STEM}_{site}_{year}.xlsx"
