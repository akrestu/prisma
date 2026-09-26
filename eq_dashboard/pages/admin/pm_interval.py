"""Interval PM per model (untuk PM Accuracy) dan pengelompokan reason standby client/internal."""
import pandas as pd
import streamlit as st
from sqlalchemy import delete, distinct, select

from core.config import DEFAULT_CLIENT_STANDBY
from core.ingest import audit
from core.ui import require
from db import models as m
from db import repo
from db.engine import session_scope

user = require("pm_interval")
st.title("Interval PM & standby")
tab_pm, tab_sb = st.tabs(["Interval PM per model", "Kelompok standby"])

with tab_pm:
    st.caption("PM (reason 502) dianggap akurat bila selisih HM sejak PM sebelumnya berada dalam interval ± toleransi. "
               "Model tanpa interval tidak dinilai.")
    with session_scope() as s:
        cur = repo.frame(s, select(m.PMInterval.model, m.PMInterval.interval_hm, m.PMInterval.tolerance_pct))
        models = sorted(x for x in s.scalars(select(distinct(m.FactEvent.model))) if x)
    grid = pd.DataFrame({"model": models}).merge(cur, on="model", how="outer").sort_values("model")
    ed = st.data_editor(grid, hide_index=True, width="stretch", num_rows="dynamic", key="pm_grid",
                        column_config={"model": st.column_config.TextColumn("Model", required=True),
                                       "interval_hm": st.column_config.NumberColumn("Interval (HM)", min_value=1),
                                       "tolerance_pct": st.column_config.NumberColumn("Toleransi (%)", min_value=0,
                                                                                      max_value=100, default=10.0)})
    if st.button("Simpan interval PM", type="primary"):
        keep = ed.dropna(subset=["model", "interval_hm"])
        with session_scope() as s:
            s.execute(delete(m.PMInterval))
            for r in keep.itertuples():
                s.add(m.PMInterval(model=r.model, interval_hm=float(r.interval_hm),
                                   tolerance_pct=float(r.tolerance_pct) if pd.notna(r.tolerance_pct) else 10.0))
            audit(s, user.username, "edit_pm_interval", None, f"{len(keep)} model")
        st.cache_data.clear()
        st.success(f"{len(keep)} interval PM disimpan.")

with tab_sb:
    st.caption("Standby karena client (mis. unit siap tapi tidak dibutuhkan) dipisahkan dari standby internal.")
    with session_scope() as s:
        cur = repo.frame(s, select(m.StandbyGroup.reason_code, m.StandbyGroup.grp))
        reasons = repo.frame(s, select(m.FactEvent.reason_code, m.FactEvent.reason_text)
                             .where(m.FactEvent.category == "S").distinct())
    reasons = reasons.dropna().drop_duplicates("reason_code").sort_values("reason_code")
    if cur.empty:
        cur = pd.DataFrame({"reason_code": list(DEFAULT_CLIENT_STANDBY), "grp": "client"})
    grid = reasons.merge(cur, on="reason_code", how="left").fillna({"grp": "internal"})
    ed = st.data_editor(grid, hide_index=True, width="stretch", disabled=["reason_code", "reason_text"], key="sb_grid",
                        column_config={"reason_code": "Kode", "reason_text": "Reason",
                                       "grp": st.column_config.SelectboxColumn("Kelompok", options=["client", "internal"])})
    if st.button("Simpan kelompok standby", type="primary"):
        with session_scope() as s:
            s.execute(delete(m.StandbyGroup))
            for r in ed.itertuples():
                s.add(m.StandbyGroup(reason_code=int(r.reason_code), grp=r.grp))
            audit(s, user.username, "edit_standby_group", None, f"{(ed['grp'] == 'client').sum()} kode client")
        st.cache_data.clear()
        st.success("Kelompok standby disimpan.")
