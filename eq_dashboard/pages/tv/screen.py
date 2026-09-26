"""Draw the TV screen for one site. Used by kiosk mode (Display link) and TV Preview."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from core import tv
from core.tv_render import render
from db import models as m
from db.engine import session_scope


@st.cache_data(ttl=3600, show_spinner=False)
def _payload(site: str, period: str, version_key: tuple) -> tv.TvData:
    """Cached per site × period × published version (+ config). Never per user, so safe to share."""
    with session_scope() as s:
        iv = pd.DataFrame([(p.model, p.interval_hm, p.tolerance_pct) for p in s.scalars(select(m.PMInterval))],
                          columns=["model", "interval_hm", "tolerance_pct"])
        return tv.build(s, site, iv, period)


def version_key(site: str) -> tuple:
    """Changes on every publish/rollback and on target, plan or PM-interval changes."""
    with session_scope() as s:
        pub = tuple((int(uid), str(ts)) for uid, ts in s.execute(
            select(m.UploadSite.upload_id, m.UploadSite.reviewed_at)
            .where(m.UploadSite.site_code == site, m.UploadSite.status == "PUBLISHED")
            .order_by(m.UploadSite.upload_id)))
        cfg = tuple(int(x or 0) for x in (s.scalar(select(func.count()).select_from(m.Target).where(m.Target.site == site)),
               s.scalar(select(func.sum(m.Target.id)).where(m.Target.site == site)),
               s.scalar(select(func.count()).select_from(m.PlanProduction).where(m.PlanProduction.site == site)),
               s.scalar(select(func.count()).select_from(m.PMInterval))))
    return pub, cfg


def show(site: str, kiosk: bool, period: str = "daily") -> None:
    st.html(render(_payload(site, period, version_key(site)), kiosk=kiosk))
