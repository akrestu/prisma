"""Data status: published data per site & month within the user's access."""
import pandas as pd
import streamlit as st

from auth.access import ROLE_LABEL
from core import dash
from core.ui import require, sites_for
from db import repo
from db.engine import session_scope

user = require("home")
sites = sites_for(user)
st.title(f"Welcome, {user.name}")
st.caption(f"{ROLE_LABEL[user.role]} · site access: {', '.join(sites) if sites else 'none yet'}")

if not sites:
    st.warning("Your account has no site access yet. Contact your Admin.")
    st.stop()

with session_scope() as s:
    pub = repo.published_versions(s, sites)
    pending = repo.pending_count(s, sites)

latest = pub.sort_values("reviewed_at").iloc[-1] if len(pub) else None
dash.summary(f"{len(pub)} site-month(s) published" if len(pub) else "Nothing published yet",
             f"latest {latest['site']} {latest['month']:%b %Y}, approved {latest['reviewed_at']:%d %b %H:%M}"
             if latest is not None and pd.notna(latest["reviewed_at"]) else "",
             f"{pending} upload(s) waiting for approval" if pending and user.role in ("admin", "site_manager") else "")

st.subheader("Published data")
if pub.empty:
    st.caption("No PUBLISHED data yet.")
else:
    pub = pub.assign(Month=pd.to_datetime(pub["month"]).dt.strftime("%B %Y"))
    grid = pub.pivot_table(index="Month", columns="site", values="upload_id", aggfunc="first")
    st.dataframe(grid.map(lambda v: f"upload #{int(v)}" if pd.notna(v) else "—"), width="stretch")

if user.role == "admin":
    import datetime as dt

    from sqlalchemy import func, select

    from auth.security import is_locked
    from core.config import WIB
    from db import models as m

    st.subheader("System health")
    now = dt.datetime.now(dt.UTC)
    with session_scope() as s:
        A = m.AuditLog
        last_bk = s.execute(select(A.ts, A.action, A.detail).where(A.action.in_(["backup_ok", "backup_failed"]))
                            .order_by(A.ts.desc()).limit(1)).first()
        failed_24h = s.scalar(select(func.count()).select_from(A).where(
            A.action.in_(["login_failed", "account_locked"]), A.ts > now - dt.timedelta(hours=24))) or 0
        locked = sum(is_locked(u) for u in s.scalars(select(m.User).where(m.User.active)))
        tvs = list(s.execute(select(m.DisplayDevice.name, m.DisplayDevice.last_seen).where(m.DisplayDevice.active)))
    offline = [n for n, seen in tvs if seen is None or now - seen > dt.timedelta(minutes=15)]

    h = st.columns(4)
    if last_bk is None:
        h[0].metric("Last backup", "never", "backup.sh not running yet", delta_color="orange", delta_arrow="off")
    else:
        age = now - last_bk.ts
        stale = last_bk.action == "backup_failed" or age > dt.timedelta(hours=36)
        h[0].metric("Last backup", f"{last_bk.ts.astimezone(WIB):%d %b %H:%M}",
                    ("FAILED: " if last_bk.action == "backup_failed" else "") + (last_bk.detail or ""),
                    delta_color="orange" if stale else "gray", delta_arrow="off",
                    help="Written by deploy/backup.sh. Orange when the last run failed or is older than 36 hours.")
    h[1].metric("TVs offline", f"{len(offline)} of {len(tvs)}", ", ".join(offline[:3]) or "all online",
                delta_color="orange" if offline else "gray", delta_arrow="off",
                help="Active TV links not seen for 15 minutes")
    h[2].metric("Locked accounts", locked, delta_color="off")
    h[3].metric("Failed sign-ins (24 h)", failed_24h,
                "check the audit log" if failed_24h >= 10 else None, delta_color="orange", delta_arrow="off")
