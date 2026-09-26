"""Admin only: delete all uploaded data (every upload, version and derived table). Settings are kept."""
import streamlit as st
from sqlalchemy import func, select

from core.ingest import audit
from core.ui import fmt_num, require
from db import models as m
from db import repo
from db.engine import session_scope

PHRASE = "DELETE ALL DATA"

user = require("delete_data")
st.title("Delete data")

done = st.session_state.pop("delete_done", None)
if done:
    st.success(f"All data deleted: {done}.")

with session_scope() as s:
    n_up = s.scalar(select(func.count()).select_from(m.Upload)) or 0
    n_ev = s.scalar(select(func.count()).select_from(m.FactEvent)) or 0
    n_rit = s.scalar(select(func.count()).select_from(m.FactRitase)) or 0
    months = s.scalar(select(func.count(func.distinct(m.UploadSite.month)))) or 0

c = st.columns(4)
c[0].metric("Uploads", fmt_num(n_up))
c[1].metric("Months", fmt_num(months))
c[2].metric("Event rows", fmt_num(n_ev))
c[3].metric("Ritase rows", fmt_num(n_rit))

st.markdown(
    "**Deleted:** every upload and version (PUBLISHED, PENDING, REJECTED, SUPERSEDED), events, stoppages, ritase, "
    "coal tickets, fuel, units and data quality findings, for all sites.  \n"
    "**Kept:** users and roles, sites and mapping, targets and production plans, PM intervals, standby groups, "
    "TV devices and the audit log.")
st.warning("This cannot be undone. Dashboards and TVs will show no data until a new Data_Prod workbook is uploaded "
           "and approved. Keep the original Excel files before deleting.")

if n_up == 0:
    st.info("There is no uploaded data to delete.")
    st.stop()

with st.form("delete_all"):
    typed = st.text_input(f"Type **{PHRASE}** to confirm")
    go = st.form_submit_button("Delete all data", type="primary")
if go:
    if typed.strip() != PHRASE:
        st.error(f"Type {PHRASE} exactly to confirm.")
    else:
        with session_scope() as s:
            counts = repo.delete_all_data(s)
            detail = ", ".join(f"{k} {v:,}" for k, v in counts.items() if v)
            audit(s, user.username, "delete_all_data", None, detail)
        st.cache_data.clear()
        st.session_state["delete_done"] = f"{counts.get('uploads', 0):,} uploads, " \
                                          f"{counts.get('fact_event', 0):,} event rows"
        st.rerun()
