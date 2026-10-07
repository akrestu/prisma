"""Draw the TV screen for one site. Used by kiosk mode (Display link) and TV Preview."""
from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from core import tv
from core.tv_render import render
from db import models as m
from db import repo
from db.engine import session_scope


@st.cache_data(ttl=3600, max_entries=40, show_spinner=False)
def _payload(site: str, period: str, version_key: tuple, review: tuple | None = None) -> tv.TvData:
    """Cached per site × period × review range × published version (+ config). Never per user, so safe to share."""
    with session_scope() as s:
        iv = pd.DataFrame([(p.model, p.interval_hm, p.tolerance_pct) for p in s.scalars(select(m.PMInterval))],
                          columns=["model", "interval_hm", "tolerance_pct"])
        return tv.build(s, site, iv, period, *(review or (None, None)))


def version_key(site: str) -> tuple:
    """Changes on every publish/rollback, on any edit of targets, plans or PM intervals (values, not counts), and on
    every Hourly Production save or cutover change."""
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
            repo.hourly_stamp(s, [site]),            # ritase from the cutover date on comes from Hourly Production
        )
    cfg = hashlib.sha1(repr(rows).encode(), usedforsecurity=False).hexdigest()
    return pub, cfg


def show(site: str, kiosk: bool, period: str = "daily", review: tuple | None = None) -> None:
    """`review` = (from, to) shows that fixed range, marked REVIEW on screen; None follows the live data."""
    review = tuple(review) if review and all(review) else None
    st.html(render(_payload(site, period, version_key(site), review), kiosk=kiosk))


# ------------------------------------------------------------------ hourly production screen
SCREENS = {"equipment": "Equipment & monthly", "hourly": "Hourly Production"}


@st.cache_data(ttl=60, max_entries=40, show_spinner=False)
def _hourly_payload(site: str, date, shift: str | None, minute_key: str, stamp: str):
    """Cached for at most a minute per site × shift; `stamp` changes on every save, so new input shows at once."""
    from core import hourly_tv
    from core.config import now_wib
    with session_scope() as s:
        return hourly_tv.build(s, site, now_wib(), date, shift)


def _hourly_stamp(site: str) -> str:
    with session_scope() as s:
        h, t = m.HourlyShift, m.Target
        last = s.scalar(select(func.max(h.updated_at)).where(h.site == site))
        cfg = s.execute(select(func.count(), func.max(m.LoaderTarget.target_per_hour))
                        .where(m.LoaderTarget.site == site)).first()
        tg = s.execute(select(t.sr, t.distance).where(t.site == site)).all()
    return f"{last}|{tuple(cfg)}|{hashlib.sha1(repr(tg).encode(), usedforsecurity=False).hexdigest()}"


def show_hourly(site: str, kiosk: bool, date=None, shift: str | None = None) -> None:
    from core.config import now_wib
    from core.hourly_render import render as render_hourly
    now = now_wib()
    d = _hourly_payload(site, date, shift, now.strftime("%Y%m%d%H%M"), _hourly_stamp(site))
    st.html(render_hourly(d, kiosk=kiosk, now=now), unsafe_allow_javascript=True)   # remark text shrinks to fit
