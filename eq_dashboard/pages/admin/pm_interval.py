"""PM interval per model (for PM accuracy) and client/internal grouping of standby reasons."""
import pandas as pd
import streamlit as st
from sqlalchemy import delete, select

from core.config import DEFAULT_CLIENT_STANDBY
from core.ingest import audit
from core.ui import require
from db import models as m
from db import repo
from db.engine import session_scope

user = require("pm_interval")
st.title("PM intervals & standby")
tab_pm, tab_sb = st.tabs(["PM interval per model", "Standby groups"])

with tab_pm:
    st.caption("A PM (reason 502) is accurate when the HM since the previous PM is within the interval ± tolerance. "
               "Models without an interval are not assessed.")
    with session_scope() as s:
        cur = repo.frame(s, select(m.PMInterval.model, m.PMInterval.interval_hm, m.PMInterval.tolerance_pct))
        models = sorted(x for x in s.scalars(select(m.FactEvent.model).distinct()) if x)
    grid = pd.DataFrame({"model": models}).merge(cur, on="model", how="outer").sort_values("model")
    ed = st.data_editor(grid, hide_index=True, width="stretch", num_rows="dynamic", key="pm_grid",
                        column_config={"model": st.column_config.TextColumn("Model", required=True),
                                       "interval_hm": st.column_config.NumberColumn("Interval (HM)", min_value=1),
                                       "tolerance_pct": st.column_config.NumberColumn("Tolerance (%)", min_value=0,
                                                                                      max_value=100, default=10.0)})
    if st.button("Save PM intervals", type="primary"):
        keep = ed.dropna(subset=["model", "interval_hm"])
        with session_scope() as s:
            s.execute(delete(m.PMInterval))
            for r in keep.itertuples():
                s.add(m.PMInterval(model=r.model, interval_hm=float(r.interval_hm),
                                   tolerance_pct=float(r.tolerance_pct) if pd.notna(r.tolerance_pct) else 10.0))
            audit(s, user.username, "edit_pm_interval", None, f"{len(keep)} models")
        st.cache_data.clear()
        st.success(f"{len(keep)} PM intervals saved.")

with tab_sb:
    st.caption("Standby caused by the client (e.g. unit available but not required) is separated from internal standby.")
    with session_scope() as s:
        cur = repo.frame(s, select(m.StandbyGroup.reason_code, m.StandbyGroup.grp))
        reasons = repo.frame(s, select(m.FactEvent.reason_code, m.FactEvent.reason_text)
                             .where(m.FactEvent.category == "S").distinct())
    reasons = reasons.dropna().drop_duplicates("reason_code").sort_values("reason_code")
    if cur.empty:
        cur = pd.DataFrame({"reason_code": list(DEFAULT_CLIENT_STANDBY), "grp": "client"})
    grid = reasons.merge(cur, on="reason_code", how="left").fillna({"grp": "internal"})
    ed = st.data_editor(grid, hide_index=True, width="stretch", disabled=["reason_code", "reason_text"], key="sb_grid",
                        column_config={"reason_code": "Code", "reason_text": "Reason",
                                       "grp": st.column_config.SelectboxColumn("Group", options=["client", "internal"])})
    if st.button("Save standby groups", type="primary"):
        with session_scope() as s:
            s.execute(delete(m.StandbyGroup))
            for r in ed.itertuples():
                s.add(m.StandbyGroup(reason_code=int(r.reason_code), grp=r.grp))
            audit(s, user.username, "edit_standby_group", None, f"{(ed['grp'] == 'client').sum()} client codes")
        st.cache_data.clear()
        st.success("Standby groups saved.")
