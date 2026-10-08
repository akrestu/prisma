"""Production Data targets: default productivity per equipment model (internal and client, company-wide), monthly
availability & reliability targets per site (import Target.xlsx / edit) and the OB & coal production plan."""
import datetime as dt

import pandas as pd
import streamlit as st
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core import hourly as H
from core import prod_target as PT
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
st.title("Production targets")
st.caption("Targets of Production Data. Hourly Production has its own targets in Setup → Hourly targets.")
if not sites:
    st.info("No sites yet.")
    st.stop()

tab_d, tab_t, tab_p = st.tabs(["Productivity defaults", "Availability & reliability", "Production plan"])

LOADER_VALUES = {"pdty_ob": "OB BCM/h", "pdty_mud": "Mud BCM/h", "pdty_coal": "Coal t/h"}
HAULER_VALUES = {"pdty_ob": "OB BCM/h", "pdty_coal": "Coal t/h"}


def defaults_grid(table: pd.DataFrame, values: dict[str, str], pop_models: list[str]) -> pd.DataFrame:
    """Wide grid of a defaults table plus an empty row for every population model not covered yet."""
    g = PT.wide(table, values)
    extra = [mo for mo in pop_models if PT.match(mo, g["model"]) is None]
    return PT.numeric(pd.concat([g, pd.DataFrame({"model": extra})], ignore_index=True)) if extra else g


with tab_d:
    with session_scope() as s:
        ld_t, hl_t = repo.model_targets(s), repo.hauler_targets(s)
        units = repo.population_for(s, today_wib())
        bases = repo.frame(s, select(m.Site.code, m.Site.target_basis).where(m.Site.code.in_(sites))
                           .order_by(m.Site.code))
    u = units if units is not None else pd.DataFrame(columns=["type", "model"])
    is_loader = u["type"].fillna("").str.contains("Load", case=False)
    pop_loaders = sorted(u.loc[is_loader, "model"].dropna().unique()) if len(u) else []
    pop_haulers = sorted(u.loc[H.is_hauler(u), "model"].dropna().unique()) if len(u) else []
    st.caption("Standard productivity per equipment model, the same for every site: the yardstick of the "
               "Production Data dashboards (Loader & hauler productivity) and the fallback of Hourly Production "
               "where a site has no hourly target. It changes rarely. A model name also covers longer unit models "
               "('SK520' covers SK520XDLC-10). Models of the unit population without a value are listed empty ('None' in a cell = no value).")
    num = lambda lbl: st.column_config.NumberColumn(lbl, min_value=0, format="%.0f")  # noqa: E731

    can_edit = user.is_admin       # company-wide values: a Site Manager sees them but cannot change other sites'
    if not can_edit:
        st.info("The defaults apply to every site, so only an Admin can change them.")

    def editor(table, values, pop_models, key):
        g = defaults_grid(table, values, pop_models)
        return st.data_editor(g, num_rows="dynamic" if can_edit else "fixed", hide_index=True, width="stretch",
                              key=key, disabled=not can_edit,
                              column_config={"model": st.column_config.TextColumn("Model", required=True),
                                             **{c: num(c) for c in g.columns if c != "model"}})

    def save_defaults(**kw) -> None:
        with st.spinner("Saving defaults…"), session_scope() as s:
            n = repo.save_default_targets(s, **kw)
            audit(s, user.username, "default_targets", None, ", ".join(f"{k} {v}" for k, v in n.items()))
        refresh("plan")
        st.success("Saved: " + ", ".join(f"{v} {k} rows" for k, v in n.items()) + ".")

    st.markdown("**Excavators** · OB and mud in BCM per hour, coal in ton per hour (empty coal = the OB value)")
    ed_l = editor(ld_t, LOADER_VALUES, pop_loaders, "pd_loaders")
    if can_edit and st.button("Save excavator defaults", type="primary", key="pd_loaders_save"):
        save_defaults(loaders=PT.long(ed_l, LOADER_VALUES))
    st.markdown("**Haulers** · OB in BCM per hour, coal in ton per hour")
    ed_h = editor(hl_t, HAULER_VALUES, pop_haulers, "pd_haulers")
    if can_edit and st.button("Save hauler defaults", type="primary", key="pd_haulers_save"):
        save_defaults(haulers=PT.long(ed_h, HAULER_VALUES))

    st.markdown("**Target basis per site** · which value counts for achievement on dashboards and TVs")
    bases["target_basis"] = bases["target_basis"].fillna("internal")
    ed_b = st.data_editor(bases, hide_index=True, width="content", key="pd_bases", disabled=["code"],
                          column_config={"code": st.column_config.TextColumn("Site"),
                                         "target_basis": st.column_config.SelectboxColumn(
                                             "Basis", options=list(PT.BASES), required=True,
                                             help="internal = WBK target, client = BAU target")})
    if st.button("Save target basis", key="pd_bases_save"):
        with session_scope() as s:
            for r in ed_b.itertuples():
                s.get(m.Site, r.code).target_basis = r.target_basis
            audit(s, user.username, "target_basis", None,
                  ", ".join(f"{r.code} {r.target_basis}" for r in ed_b.itertuples()))
        refresh("plan")
        st.success("Target basis saved.")


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
    a, b, c = st.columns(3)
    site_p = a.selectbox("Site", sites, key="plan_site")
    year_p = b.number_input("Year", 2018, 2100, today_wib().year, key="plan_year")
    month_p = c.selectbox("Month", range(1, 13), index=today_wib().month - 1, key="plan_month",
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
            refresh("plan")
            st.success("Plan saved.")
