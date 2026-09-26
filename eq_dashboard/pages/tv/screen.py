"""Gambar layar TV untuk satu site. Dipakai oleh mode kiosk (link Display) dan Preview TV."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import select

from core import tv
from core.tv_render import render
from db import models as m
from db.engine import session_scope


@st.cache_data(ttl=3600, show_spinner=False)
def _payload(site: str, version_key: tuple) -> tv.TvData:
    """Cache per site × versi published (+ konfigurasi). Bukan per user, jadi aman dipakai bersama."""
    with session_scope() as s:
        iv = pd.DataFrame([(p.model, p.interval_hm, p.tolerance_pct) for p in s.scalars(select(m.PMInterval))],
                          columns=["model", "interval_hm", "tolerance_pct"])
        return tv.build(s, site, iv)


def version_key(site: str) -> tuple:
    """Berubah setiap ada publish/rollback, perubahan target, plan, atau interval PM."""
    from sqlalchemy import func

    with session_scope() as s:
        pub = s.execute(select(m.UploadSite.upload_id, m.UploadSite.reviewed_at)
                        .where(m.UploadSite.site_code == site, m.UploadSite.status == "PUBLISHED")
                        .order_by(m.UploadSite.month.desc()).limit(1)).first()
        cfg = (s.scalar(select(func.count()).select_from(m.Target).where(m.Target.site == site)),
               s.scalar(select(func.max(m.Target.id)).where(m.Target.site == site)),
               s.scalar(select(func.count()).select_from(m.PlanProduction).where(m.PlanProduction.site == site)),
               s.scalar(select(func.count()).select_from(m.PMInterval)))
    return (tuple(pub) if pub else None, cfg)


def show(site: str, kiosk: bool) -> None:
    data = _payload(site, version_key(site))
    st.html(render(data, kiosk=kiosk))
