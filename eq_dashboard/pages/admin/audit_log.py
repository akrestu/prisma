"""Audit log: sign-ins, uploads, approvals, user/target/configuration changes."""
import datetime as dt

import pandas as pd
import streamlit as st
from sqlalchemy import select

from core.config import UNMAPPED
from core.ui import excel_download, require, sites_for
from db import models as m
from db import repo
from db.engine import session_scope

user = require("audit_log")
st.title("Audit log")
st.caption("Who changed what and when: uploads, approvals, setup changes and deletions.")
a, b, c = st.columns(3)
days = a.selectbox("Period", [1, 7, 30, 90, 365], index=2, format_func=lambda d: f"last {d} days")
since = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
q = select(m.AuditLog.ts, m.AuditLog.username, m.AuditLog.action, m.AuditLog.site, m.AuditLog.detail) \
    .where(m.AuditLog.ts >= since).order_by(m.AuditLog.ts.desc()).limit(5000)
if not user.is_admin:  # Site Manager: own sites only
    q = q.where(m.AuditLog.site.in_([x for x in sites_for(user) if x != UNMAPPED]))
with session_scope() as s:
    df = repo.frame(s, q)
if df.empty:
    st.info("No entries.")
    st.stop()
act = b.multiselect("Action", sorted(df["action"].unique()))
who = c.multiselect("User", sorted(df["username"].dropna().unique()))
if act:
    df = df[df["action"].isin(act)]
if who:
    df = df[df["username"].isin(who)]
df["ts"] = pd.to_datetime(df["ts"]).dt.tz_convert("Asia/Jakarta").dt.strftime("%d %b %Y %H:%M:%S")
df.columns = ["Time (WIB)", "User", "Action", "Site", "Detail"]
st.dataframe(df, hide_index=True, width="stretch", height=520)
excel_download(df, "audit_log.xlsx")
