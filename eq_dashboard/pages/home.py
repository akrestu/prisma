"""Beranda: status data per site & bulan sesuai hak akses."""
import pandas as pd
import streamlit as st

from auth.access import ROLE_LABEL
from core.ui import require, sites_for
from db import repo
from db.engine import session_scope

user = require("home")
sites = sites_for(user)
st.title(f"Selamat datang, {user.name}")
st.caption(f"{ROLE_LABEL[user.role]} · akses site: {', '.join(sites) if sites else 'belum ada'}")

if not sites:
    st.warning("Akun Anda belum diberi akses site. Hubungi Admin.")
    st.stop()

with session_scope() as s:
    pub = repo.published_versions(s, sites)
    pending = repo.pending_count(s, sites)

if pending and user.role in ("admin", "site_manager"):
    st.info(f"{pending} data menunggu persetujuan di halaman Approval.")

st.subheader("Data yang sudah tayang")
if pub.empty:
    st.caption("Belum ada data PUBLISHED.")
else:
    pub = pub.assign(Bulan=pd.to_datetime(pub["month"]).dt.strftime("%B %Y"))
    grid = pub.pivot_table(index="Bulan", columns="site", values="upload_id", aggfunc="first")
    st.dataframe(grid.map(lambda v: f"upload #{int(v)}" if pd.notna(v) else "—"), width="stretch")
st.caption("Dashboard analisa dan layar TV menyusul di milestone berikutnya.")
