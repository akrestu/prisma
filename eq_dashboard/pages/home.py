"""Data status: published data per site & month within the user's access."""
import pandas as pd
import streamlit as st

from auth.access import ROLE_LABEL
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

if pending and user.role in ("admin", "site_manager"):
    st.info(f"{pending} upload(s) waiting for approval on the Approval page.")

st.subheader("Published data")
if pub.empty:
    st.caption("No PUBLISHED data yet.")
else:
    pub = pub.assign(Month=pd.to_datetime(pub["month"]).dt.strftime("%B %Y"))
    grid = pub.pivot_table(index="Month", columns="site", values="upload_id", aggfunc="first")
    st.dataframe(grid.map(lambda v: f"upload #{int(v)}" if pd.notna(v) else "—"), width="stretch")
