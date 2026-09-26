"""Query data untuk halaman. Fungsi murni (tanpa Streamlit); caching dilakukan di layer UI."""
from __future__ import annotations

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.ingest import PENDING, PUBLISHED
from db import models as m


def frame(s: Session, stmt) -> pd.DataFrame:
    res = s.execute(stmt)
    return pd.DataFrame(res.fetchall(), columns=list(res.keys()))


def upload_sites(s: Session, sites: list[str], statuses: list[str] | None = None,
                 uploader_id: int | None = None) -> pd.DataFrame:
    q = (select(m.UploadSite.id, m.UploadSite.upload_id, m.UploadSite.site_code.label("site"),
                m.UploadSite.month, m.UploadSite.status, m.UploadSite.auto_approved, m.UploadSite.comment,
                m.UploadSite.reviewed_at, m.UploadSite.summary, m.UploadSite.dq_summary,
                m.Upload.filename, m.Upload.uploaded_at, m.User.full_name.label("uploader"),
                m.Upload.uploaded_by)
         .join(m.Upload, m.Upload.id == m.UploadSite.upload_id)
         .outerjoin(m.User, m.User.id == m.Upload.uploaded_by)
         .where(m.UploadSite.site_code.in_(sites))
         .order_by(m.Upload.id.desc(), m.UploadSite.site_code))
    if statuses:
        q = q.where(m.UploadSite.status.in_(statuses))
    if uploader_id is not None:
        q = q.where(m.Upload.uploaded_by == uploader_id)
    return frame(s, q)


def pending_count(s: Session, sites: list[str]) -> int:
    return s.scalar(select(func.count()).select_from(m.UploadSite)
                    .where(m.UploadSite.site_code.in_(sites), m.UploadSite.status == PENDING)) or 0


def published_versions(s: Session, sites: list[str]) -> pd.DataFrame:
    """Versi PUBLISHED per site × bulan (satu baris per kombinasi)."""
    return frame(s, select(m.UploadSite.site_code.label("site"), m.UploadSite.month, m.UploadSite.upload_id,
                           m.UploadSite.reviewed_at, m.UploadSite.auto_approved)
                 .where(m.UploadSite.site_code.in_(sites), m.UploadSite.status == PUBLISHED)
                 .order_by(m.UploadSite.month.desc(), m.UploadSite.site_code))


def events(s: Session, upload_id: int, site: str) -> pd.DataFrame:
    t = m.FactEvent
    return frame(s, select(t.site, t.date, t.shift, t.week, t.seq, t.unit_id, t.type, t.model, t.hours,
                           t.hm_start, t.status, t.category, t.reason_code, t.reason_text)
                 .where(t.upload_id == upload_id, t.site == site))


def stoppages(s: Session, upload_id: int, site: str) -> pd.DataFrame:
    t = m.FactStoppage
    return frame(s, select(t.site, t.unit_id, t.type, t.model, t.start_date, t.hours, t.sm_hours, t.usm_hours,
                           t.main_reason).where(t.upload_id == upload_id, t.site == site))


def dq_findings(s: Session, upload_id: int, site: str) -> pd.DataFrame:
    t = m.DQFinding
    return frame(s, select(t.severity, t.rule, t.sheet, t.row_ref, t.unit_id, t.date, t.detail)
                 .where(t.upload_id == upload_id, t.site == site)
                 .order_by(t.severity, t.rule, t.row_ref))


# ---------------------------------------------------------------- data explorer (read-only raw tables)
EXPLORER_TABLES = {
    "Events": (m.FactEvent, "date"),
    "Stoppages": (m.FactStoppage, "start_date"),
    "Ritase (trips per hour)": (m.FactRitase, "date"),
    "Coal tickets": (m.FactCoalTicket, "date"),
    "Fuel consumption": (m.FactFuel, "date"),
    "Fuel receipts": (m.FactFuelReceipt, "date"),
    "Units (population)": (m.DimUnit, None),
    "Data quality findings": (m.DQFinding, "date"),
}
_HIDDEN = {"id", "upload_id", "month"}


def explorer_rows(s: Session, table: str, versions: list[tuple[int, str]], date_from=None, date_to=None,
                  limit: int = 200_000) -> pd.DataFrame:
    """Raw rows of one table for the given (upload_id, site) versions, optionally within a date range."""
    from sqlalchemy import and_, or_
    model, date_col = EXPLORER_TABLES[table]
    cols = [c for c in model.__table__.columns if c.key not in _HIDDEN]
    if not versions:
        return pd.DataFrame(columns=[c.key for c in cols])
    q = select(*cols).where(or_(*[and_(model.upload_id == u, model.site == st_) for u, st_ in versions]))
    if date_col and date_from is not None and date_to is not None:
        dc = getattr(model, date_col)
        q = q.where(dc >= date_from, dc <= date_to)
    order = [getattr(model, date_col)] if date_col else []
    return frame(s, q.order_by(model.site, *order, model.id).limit(limit))


def delete_all_data(s: Session) -> dict[str, int]:
    """Remove every upload and all data derived from it. Users, sites, targets, plans and settings stay."""
    from sqlalchemy import delete
    counts = {}
    for model in (m.FactEvent, m.FactStoppage, m.FactRitase, m.FactCoalTicket, m.FactFuel, m.FactFuelReceipt,
                  m.DimUnit, m.DQFinding, m.UploadSite, m.Upload):
        counts[model.__tablename__] = s.execute(delete(model)).rowcount or 0
    return counts


EXPORT_TABLES = {"units": "Units (population)", "events": "Events", "ritase": "Ritase (trips per hour)",
                 "coal": "Coal tickets", "fuel": "Fuel consumption", "receipt": "Fuel receipts"}


def export_tables(s: Session, versions: list[tuple[int, str]]) -> dict[str, pd.DataFrame]:
    """Stored tables of the given versions, keyed for core.dataprod.export_workbook."""
    return {k: explorer_rows(s, t, versions, limit=2_000_000) for k, t in EXPORT_TABLES.items()}


def latest_units(s: Session, sites: list[str]) -> pd.DataFrame:
    """Unit population of the newest PUBLISHED version per site (pre-fills the template)."""
    pub = published_versions(s, sites)
    if pub.empty:
        return pd.DataFrame()
    newest = pub.sort_values("month").groupby("site").tail(1)
    return explorer_rows(s, "Units (population)", [(int(r.upload_id), r.site) for r in newest.itertuples()])
