"""Operator master per site: NRP, name, position. Hourly Production input picks operators by NRP, so operator KPIs stay
correct whatever spelling a name has."""

import logging

import pandas as pd
import streamlit as st

from core.config import UNMAPPED
from core.ingest import audit
from core.io import read_workbook, text
from core.ui import excel_bytes, require, sites_for
from db import models as m
from db import repo
from db.engine import session_scope

POSITIONS = ["Operator Excavator", "Operator Dump Truck", "Operator Dozer", "Operator Grader", "Operator Other"]

user = require("operators")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title("Operators")
st.caption("One row per operator. The NRP is the key used by Hourly Production input and, later, by operator KPIs.")
if not sites:
    st.info("No site access.")
    st.stop()
msg = st.session_state.pop("op_msg", None)
if msg:
    st.success(msg)

site = st.selectbox("Site", sites, key="op_site")
with session_scope() as s:
    cur = repo.operators(s, site, active_only=False)

t_edit, t_imp = st.tabs([f"Operators ({int(cur['active'].sum()) if len(cur) else 0} active)", "Import from Excel"])


def save(df: pd.DataFrame, how: str) -> None:
    df = df.copy()
    df["nrp"] = text(df["nrp"].astype("string")).str.replace(r"\.0$", "", regex=True)
    df["name"] = text(df["name"].astype("string"))
    df = df.dropna(subset=["nrp", "name"])
    dup = df[df.duplicated("nrp", keep=False)]
    if len(dup):
        st.error(f"NRP listed more than once: {', '.join(sorted(dup['nrp'].unique()))}.")
        return
    df["active"] = df["active"].fillna(True).astype(bool) if "active" in df else True
    with st.spinner("Saving operators…"), session_scope() as s:
        n = repo.replace_site_rows(s, m.Operator, site, df, ["nrp", "name", "position", "active"])
        audit(s, user.username, "operators_" + how, site, f"{n} operators")
    st.session_state["op_msg"] = f"{n} operators saved for {site}."
    st.rerun()


with t_edit:
    ed = st.data_editor(cur, num_rows="dynamic", hide_index=True, width="stretch", key=f"op_ed_{site}",
                        column_config={
                            "nrp": st.column_config.TextColumn("NRP", required=True),
                            "name": st.column_config.TextColumn("Name", required=True),
                            "position": st.column_config.SelectboxColumn("Position", options=POSITIONS),
                            "active": st.column_config.CheckboxColumn("Active", default=True,
                                                                      help="Inactive operators are hidden in input "
                                                                           "but keep their history")})
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("Save operators", type="primary", key="op_save"):
        save(ed, "edit")
    c2.download_button("Download list", lambda: excel_bytes(cur.rename(columns=str.title)), on_click="ignore",
                       file_name=f"Operators_{site}.xlsx", key="op_dl",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with t_imp:
    st.markdown("An Excel sheet with the columns **NRP**, **Name** and optionally **Position** and **Active** "
                "(the *Download list* file of the first tab has exactly this layout). It replaces the operator list "
                "of the site.")
    f = st.file_uploader("Operators workbook (.xlsx)", type=["xlsx"], key="op_file", max_upload_size=5)
    if f is not None:
        try:
            with st.spinner(f"Reading {f.name}…"):
                raw = next(iter(read_workbook(f.getvalue()).values()))
        except Exception as e:  # unreadable file
            logging.getLogger(__name__).warning("workbook could not be opened", exc_info=True)
            st.error(f"The workbook could not be opened ({type(e).__name__}). Save it again as .xlsx and retry.")
            st.stop()
        df = raw.iloc[1:].copy()
        df.columns = [str(c).strip().lower() for c in raw.iloc[0]]
        if not {"nrp", "name"} <= set(df.columns):
            st.error("The first row must hold the headers NRP and Name.")
            st.stop()
        df = df.reindex(columns=["nrp", "name", "position", "active"])
        df["active"] = df["active"].map(lambda v: str(v).strip().lower() not in ("0", "false", "no", "n")
                                        if pd.notna(v) else True)
        st.dataframe(df, hide_index=True, width="stretch", height=300)
        st.caption(f"{len(df.dropna(subset=['nrp']))} operators in the file · {len(cur)} in {site} now.")
        if st.button(f"Replace operators of {site}", type="primary", key="op_imp"):
            save(df, "import")
