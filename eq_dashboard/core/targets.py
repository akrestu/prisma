"""Import Target.xlsx dan lookup target per site × bulan (NULL = belum ada target)."""
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
    "PM Accuracy Target": "pm_accuracy",
}
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
    for c in METRICS:
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df else None
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
    recs = df[["site", "year", "month", *METRICS]].astype(object).where(df.notna(), None).to_dict("records")
    stmt = pg_insert(m.Target).values(recs)
    stmt = stmt.on_conflict_do_update(index_elements=["site", "year", "month"],
                                      set_={c: stmt.excluded[c] for c in METRICS})
    s.execute(stmt)
    return len(recs)


def target_for(s: Session, site: str, year: int, month: int) -> dict[str, float | None]:
    t = s.scalar(select(m.Target).where(m.Target.site == site, m.Target.year == year, m.Target.month == month))
    return {c: (getattr(t, c) if t else None) for c in METRICS}
