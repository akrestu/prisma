"""Draw the TV screen for one site. Used by kiosk mode (Display link) and TV Preview."""
from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st
from sqlalchemy import select

from core import tv
from core.tv_render import render
from db import models as m
from db.engine import session_scope


@st.cache_data(ttl=3600, max_entries=40, show_spinner=False)
def _payload(site: str, period: str, version_key: tuple) -> tv.TvData:
    """Cached per site × period × published version (+ config). Never per user, so safe to share."""
    with session_scope() as s:
        iv = pd.DataFrame([(p.model, p.interval_hm, p.tolerance_pct) for p in s.scalars(select(m.PMInterval))],
                          columns=["model", "interval_hm", "tolerance_pct"])
        return tv.build(s, site, iv, period)


def version_key(site: str) -> tuple:
    """Changes on every publish/rollback and on any edit of targets, plans or PM intervals (values, not counts)."""
    with session_scope() as s:
        pub = tuple((int(uid), str(ts)) for uid, ts in s.execute(
            select(m.UploadSite.upload_id, m.UploadSite.reviewed_at)
            .where(m.UploadSite.site_code == site, m.UploadSite.status == "PUBLISHED")
            .order_by(m.UploadSite.upload_id)))
        T, P, PMI = m.Target, m.PlanProduction, m.PMInterval
        rows = (
            s.execute(select(T.year, T.month, T.pa, T.uoa, T.mtbs, T.mttr, T.sched_down, T.pm_accuracy)
                      .where(T.site == site).order_by(T.year, T.month)).all(),
            s.execute(select(P.year, P.month, P.date, P.ob_bcm, P.coal_ton)
                      .where(P.site == site).order_by(P.year, P.month, P.date)).all(),
            s.execute(select(PMI.model, PMI.interval_hm, PMI.tolerance_pct).order_by(PMI.model)).all(),
        )
    cfg = hashlib.sha1(repr(rows).encode(), usedforsecurity=False).hexdigest()
    return pub, cfg


def show(site: str, kiosk: bool, period: str = "daily") -> None:
    st.html(render(_payload(site, period, version_key(site)), kiosk=kiosk))
