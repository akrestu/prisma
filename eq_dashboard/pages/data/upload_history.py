"""Riwayat upload & versi per site × bulan. Admin bisa rollback ke versi sebelumnya."""
import pandas as pd
import streamlit as st

from core import ingest as ing
from core.ui import STATUS_BADGE, excel_download, require, sites_for
from db import models as m
from db import repo
from db.engine import session_scope

user = require("upload_history")
sites = sites_for(user)
st.title("Riwayat upload")

with session_scope() as s:
    df = repo.upload_sites(s, sites)
if df.empty:
    st.info("Belum ada upload.")
    st.stop()

c1, c2 = st.columns(2)
site_f = c1.multiselect("Site", sorted(df["site"].unique()))
status_f = c2.multiselect("Status", list(STATUS_BADGE))
v = df
if site_f:
    v = v[v["site"].isin(site_f)]
if status_f:
    v = v[v["status"].isin(status_f)]

table = pd.DataFrame({
    "ID": v["id"], "Upload": v["upload_id"], "File": v["filename"], "Bulan": pd.to_datetime(v["month"]).dt.strftime("%Y-%m"),
    "Site": v["site"], "Status": v["status"], "Auto": v["auto_approved"].map({True: "ya", False: ""}),
    "Diupload": pd.to_datetime(v["uploaded_at"]).dt.tz_convert("Asia/Jakarta").dt.strftime("%d %b %Y %H:%M"),
    "Oleh": v["uploader"], "Komentar": v["comment"],
    "DQ kritis": v["dq_summary"].map(lambda d: (d or {}).get("critical", 0)),
})
st.dataframe(table, hide_index=True, width="stretch")
excel_download(table, "riwayat_upload.xlsx")

if user.is_admin:
    st.subheader("Rollback")
    sup = v[v["status"] == ing.SUPERSEDED]
    if sup.empty:
        st.caption("Tidak ada versi lama (SUPERSEDED) yang bisa dikembalikan.")
    else:
        opts = {int(r.id): f"#{r.id} · {r.site} · {pd.Timestamp(r.month):%Y-%m} · upload #{r.upload_id} ({r.filename})"
                for r in sup.itertuples()}
        pick = st.selectbox("Kembalikan versi", list(opts), format_func=opts.get)
        if st.button("Rollback ke versi ini"):
            with session_scope() as s:
                ing.rollback(s, s.get(m.UploadSite, pick), user.id, user.username)
            st.cache_data.clear()
            st.success("Versi dikembalikan menjadi PUBLISHED.")
            st.rerun()
