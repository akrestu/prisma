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
