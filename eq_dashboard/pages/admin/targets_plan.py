"""Plan & KPI targets of Production Data: monthly availability & reliability targets per site (import Target.xlsx
/ edit) and the OB & coal production plan. Productivity per model is in Setup → Productivity targets."""
import datetime as dt

import pandas as pd
import streamlit as st
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.config import UNMAPPED, today_wib
from core.ingest import audit
from core.targets import METRICS, import_targets
from core.targets import build_template as targets_template
from core.targets import file_name as targets_file
from core.ui import refresh, require, sites_for
from db import models as m
from db import repo
from db.engine import session_scope

EXTRA = ("sr", "distance")  # production targets used by the hourly screen (not in Target.xlsx)

user = require("targets_plan")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title("Plan & KPI targets")
st.caption("Monthly availability & reliability targets and the OB & coal production plan per site. Productivity per "
           "equipment model is in Setup → Productivity targets.")
if not sites:
    st.info("No sites yet.")
    st.stop()

tab_t, tab_p = st.tabs(["Availability & reliability", "Production plan"])

with tab_t:
    with st.expander("Excel: import a targets workbook (Target.xlsx or the downloaded template)"):
        f = st.file_uploader("Targets file (.xlsx)", type=["xlsx"], key="tgt_file")
        dest = st.multiselect("Apply to sites (for files without a Site column)", sites, default=sites)
        if f and st.button("Import", type="primary"):
            try:
                with st.spinner("Importing targets…"), session_scope() as s:
                    n = import_targets(s, f.getvalue(), dest)
                    audit(s, user.username, "import_target", ",".join(dest), f"{f.name}: {n} rows")
                refresh("plan")
                st.success(f"{n} target rows saved (existing rows overwritten).")
            except ValueError as e:
                st.error(str(e))

    a, b = st.columns(2)
    site = a.selectbox("Site", sites, key="tgt_site")
    year = b.number_input("Year", 2018, 2100, today_wib().year, key="tgt_year")
    with session_scope() as s:
        cur = repo.frame(s, select(m.Target.month, *[getattr(m.Target, c) for c in (*METRICS, *EXTRA)])
                         .where(m.Target.site == site, m.Target.year == year))
    st.download_button(f"Download {targets_file(site, int(year))}", lambda: targets_template(site, int(year), cur),
                       file_name=targets_file(site, int(year)), on_click="ignore", key="tgt_dl",
                       help="The 12 months of this site and year with the current values: edit and import it back",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
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
                                           "sched_down": pct("Sched. down (%)"), "pm_accuracy": pct("PM accuracy (%)"),
                                           "sr": st.column_config.NumberColumn(
                                               "SR (BCM/t)", min_value=0, format="%.1f",
                                               help="Stripping ratio target for the hourly production screen"),
                                           "distance": st.column_config.NumberColumn(
                                               "Distance (m)", min_value=0, format="%.0f",
                                               help="Haul distance target for the hourly production screen")})
    if st.button("Save targets", type="primary"):
        e = edited.copy()
        for c in ("pa", "uoa", "sched_down", "pm_accuracy"):
            e[c] = e[c] / 100
        recs = e.assign(site=site, year=int(year)).astype(object).where(e.notna(), None).to_dict("records")
        with session_scope() as s:
            stmt = pg_insert(m.Target).values(recs)
            s.execute(stmt.on_conflict_do_update(index_elements=["site", "year", "month"],
                                                 set_={c: stmt.excluded[c] for c in (*METRICS, *EXTRA)}))
            audit(s, user.username, "edit_target", site, str(year))
        refresh("plan")
        st.success("Targets saved.")

with tab_p:
    import calendar
    if msg := st.session_state.pop("plan_msg", None):
        st.success(msg)
    a, b = st.columns(2)
    site_p = a.selectbox("Site", sites, key="plan_site")
    year_p = int(b.number_input("Year", 2018, 2100, today_wib().year, key="plan_year"))
    with session_scope() as s:
        rows = repo.frame(s, select(m.PlanProduction.month, m.PlanProduction.ob_bcm, m.PlanProduction.coal_ton)
                          .where(m.PlanProduction.site == site_p, m.PlanProduction.year == year_p,
                                 m.PlanProduction.date.is_(None)))
    have = rows.groupby("month")[["ob_bcm", "coal_ton"]].sum(min_count=1) if len(rows) else pd.DataFrame()
    grid = pd.DataFrame({"month": range(1, 13)})
    grid["Month"] = [dt.date(year_p, mo, 1).strftime("%B") for mo in grid["month"]]
    grid["days"] = [calendar.monthrange(year_p, mo)[1] for mo in grid["month"]]
    for col in ("ob_bcm", "coal_ton"):
        grid[col] = grid["month"].map(have[col]).astype(float) if len(have) else float("nan")
    grid["ob_day"] = grid["ob_bcm"] / grid["days"]
    grid["coal_day"] = grid["coal_ton"] / grid["days"]
    st.caption("Enter the OB and coal target of each month. The daily target is the month's target divided "
               "evenly over its calendar days, used by every dashboard and TV. Empty month = no target.")
    num = lambda lbl, fmt="%.0f": st.column_config.NumberColumn(lbl, min_value=0, format=fmt)  # noqa: E731
    ed = st.data_editor(grid, hide_index=True, width="stretch", key=f"plan_{site_p}_{year_p}",
                        column_order=["Month", "ob_bcm", "coal_ton", "days", "ob_day", "coal_day"],
                        disabled=["Month", "days", "ob_day", "coal_day"],
                        column_config={"ob_bcm": num("OB month (BCM)"), "coal_ton": num("Coal month (t)"),
                                       "days": st.column_config.NumberColumn("Days"),
                                       "ob_day": num("OB per day (BCM)"), "coal_day": num("Coal per day (t)", "%.1f")})
    st.caption("The per-day columns show the split of the values saved; they update after saving.")
    if st.button("Save plan", type="primary", key="plan_save"):
        with session_scope() as s:
            # the whole year of the site is replaced; daily plans entered before are dropped (monthly only now)
            s.execute(delete(m.PlanProduction).where(m.PlanProduction.site == site_p,
                                                     m.PlanProduction.year == year_p))
            n = 0
            for r in ed.itertuples():
                ob = None if pd.isna(r.ob_bcm) or not r.ob_bcm else float(r.ob_bcm)
                coal = None if pd.isna(r.coal_ton) or not r.coal_ton else float(r.coal_ton)
                if ob or coal:
                    s.add(m.PlanProduction(site=site_p, year=year_p, month=int(r.month), date=None,
                                           ob_bcm=ob, coal_ton=coal))
                    n += 1
            audit(s, user.username, "edit_plan", site_p, f"{year_p}: {n} month(s)")
        refresh("plan")
        st.session_state["plan_msg"] = f"Plan of {site_p} {year_p} saved: {n} month(s)."
        st.rerun()
