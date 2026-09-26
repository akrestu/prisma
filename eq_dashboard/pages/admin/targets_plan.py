"""Monthly targets per site (import Target.xlsx / edit) and OB & coal production plan."""
import datetime as dt

import pandas as pd
import streamlit as st
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.config import UNMAPPED
from core.ingest import audit
from core.targets import METRICS, import_targets
from core.ui import require, sites_for
from db import models as m
from db import repo
from db.engine import session_scope

user = require("targets_plan")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title("Targets & plan")
if not sites:
    st.info("No sites yet.")
    st.stop()

tab_t, tab_p = st.tabs(["Monthly targets", "Production plan"])

with tab_t:
    with st.expander("Import Target.xlsx"):
        f = st.file_uploader("Target file (.xlsx)", type=["xlsx"], key="tgt_file")
        dest = st.multiselect("Apply to sites (for files without a Site column)", sites, default=sites)
        if f and st.button("Import", type="primary"):
            try:
                with session_scope() as s:
                    n = import_targets(s, f.getvalue(), dest)
                    audit(s, user.username, "import_target", ",".join(dest), f"{f.name}: {n} rows")
                st.cache_data.clear()
                st.success(f"{n} target rows saved (existing rows overwritten).")
            except ValueError as e:
                st.error(str(e))

    a, b = st.columns(2)
    site = a.selectbox("Site", sites, key="tgt_site")
    year = b.number_input("Year", 2018, 2100, dt.date.today().year, key="tgt_year")
    with session_scope() as s:
        cur = repo.frame(s, select(m.Target.month, *[getattr(m.Target, c) for c in METRICS])
                         .where(m.Target.site == site, m.Target.year == year))
    grid = pd.DataFrame({"month": range(1, 13)}).merge(cur, on="month", how="left")
    for c in ("pa", "uoa", "sched_down", "pm_accuracy"):
        grid[c] = grid[c] * 100
    st.caption("Percentages are entered in % (e.g. 85). An empty cell means no target.")
    pct = lambda lbl: st.column_config.NumberColumn(lbl, min_value=0, max_value=100, format="%.1f")  # noqa: E731
    edited = st.data_editor(grid, hide_index=True, width="stretch", key=f"tgt_{site}_{year}",
                            disabled=["month"],
                            column_config={"month": st.column_config.NumberColumn("Month"),
                                           "pa": pct("PA %"), "uoa": pct("UoA %"),
                                           "mtbs": st.column_config.NumberColumn("MTBS (hrs)", min_value=0),
                                           "mttr": st.column_config.NumberColumn("MTTR (hrs)", min_value=0),
                                           "sched_down": pct("Sched. down (%)"), "pm_accuracy": pct("PM accuracy (%)")})
    if st.button("Save targets", type="primary"):
        e = edited.copy()
        for c in ("pa", "uoa", "sched_down", "pm_accuracy"):
            e[c] = e[c] / 100
        recs = e.assign(site=site, year=int(year)).astype(object).where(e.notna(), None).to_dict("records")
        with session_scope() as s:
            stmt = pg_insert(m.Target).values(recs)
            s.execute(stmt.on_conflict_do_update(index_elements=["site", "year", "month"],
                                                 set_={c: stmt.excluded[c] for c in METRICS}))
            audit(s, user.username, "edit_target", site, str(year))
        st.cache_data.clear()
        st.success("Targets saved.")

with tab_p:
    a, b, c = st.columns(3)
    site_p = a.selectbox("Site", sites, key="plan_site")
    year_p = b.number_input("Year", 2018, 2100, dt.date.today().year, key="plan_year")
    month_p = c.selectbox("Month", range(1, 13), index=dt.date.today().month - 1, key="plan_month",
                          format_func=lambda x: dt.date(2000, x, 1).strftime("%B"))
    with session_scope() as s:
        rows = repo.frame(s, select(m.PlanProduction.date, m.PlanProduction.ob_bcm, m.PlanProduction.coal_ton)
                          .where(m.PlanProduction.site == site_p, m.PlanProduction.year == year_p,
                                 m.PlanProduction.month == month_p))
    monthly = rows[rows["date"].isna()] if len(rows) else rows

    def first(col):
        return float(monthly[col].iloc[0]) if len(monthly) and pd.notna(monthly[col].iloc[0]) else 0.0

    st.markdown("**Monthly plan** (spread evenly over calendar days unless a daily plan is set)")
    x, y = st.columns(2)
    ob_m = x.number_input("OB (BCM)", 0.0, value=first("ob_bcm"), step=1000.0)
    coal_m = y.number_input("Coal (t)", 0.0, value=first("coal_ton"), step=100.0)
    st.markdown("**Daily plan** (optional, overrides the monthly plan on the dates entered)")
    daily = rows[rows["date"].notna()] if len(rows) else pd.DataFrame(columns=["date", "ob_bcm", "coal_ton"])
    ed = st.data_editor(daily.reset_index(drop=True), num_rows="dynamic", hide_index=True, width="stretch",
                        key=f"plan_{site_p}_{year_p}_{month_p}",
                        column_config={"date": st.column_config.DateColumn("Date", required=True),
                                       "ob_bcm": st.column_config.NumberColumn("OB (BCM)", min_value=0),
                                       "coal_ton": st.column_config.NumberColumn("Coal (t)", min_value=0)})
    if st.button("Save plan", type="primary"):
        ed = ed.dropna(subset=["date"])
        bad = [d for d in ed["date"] if pd.Timestamp(d).year != year_p or pd.Timestamp(d).month != month_p]
        if bad:
            st.error("All daily plan dates must be in the selected month.")
        else:
            with session_scope() as s:
                s.execute(delete(m.PlanProduction).where(m.PlanProduction.site == site_p,
                                                         m.PlanProduction.year == year_p,
                                                         m.PlanProduction.month == month_p))
                if ob_m or coal_m:
                    s.add(m.PlanProduction(site=site_p, year=year_p, month=month_p, date=None,
                                           ob_bcm=ob_m or None, coal_ton=coal_m or None))
                for r in ed.itertuples():
                    s.add(m.PlanProduction(site=site_p, year=year_p, month=month_p, date=pd.Timestamp(r.date).date(),
                                           ob_bcm=None if pd.isna(r.ob_bcm) else r.ob_bcm,
                                           coal_ton=None if pd.isna(r.coal_ton) else r.coal_ton))
                audit(s, user.username, "edit_plan", site_p, f"{year_p}-{month_p:02d}")
            st.cache_data.clear()
            st.success("Plan saved.")
