"""OB production from ritase: daily BCM vs plan, hourly profile, material, pit, disposal, hauler, haul distance."""
import calendar

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import dash
from core import theme as T
from core.periods import weighted
from core.ui import excel_download, fmt_num
from core.validate import HOUR_SLOTS

c = dash.context("production_ob", unit_filter=False)
st.title("OB production")
ob = c.rit[c.rit["material_group"] == "OB"] if len(c.rit) else c.rit
if ob.empty:
    st.info("No OB trips for this selection.")
    st.stop()

daily = ob.groupby("date")["volume"].sum()
plan = dash.plan_range(c.sites, c.date_from, c.date_to).set_index("date")["ob_plan"]
plan_mtd = plan.reindex(daily.index).sum(min_count=1)
# a month-end projection only makes sense while looking at the current month to date
projectable = c.preset == "mtd"
days_in_month = calendar.monthrange(c.month.year, c.month.month)[1]
proj = daily.mean() * days_in_month
top_pit = ob.groupby("pit")["volume"].sum().sort_values(ascending=False)
dash.summary(f"{fmt_num(daily.sum())} BCM over {len(daily)} days, {fmt_num(daily.mean())} BCM per day",
             (f"projected {fmt_num(proj)} BCM at month end" if projectable else "")
             + (f" against a plan of {fmt_num(plan.sum())} BCM" if projectable and plan.notna().any() else ""),
             f"{top_pit.index[0]} delivers {top_pit.iloc[0] / top_pit.sum():.0%}" if len(top_pit) else "")
r = st.columns(6)
r[0].metric("OB in period", f"{fmt_num(daily.sum())} BCM")
r[1].metric("Average per day", f"{fmt_num(daily.mean())} BCM")
r[2].metric("Trips", fmt_num(ob["rit"].sum()))
if pd.notna(plan_mtd) and plan_mtd:
    r[3].metric("Achievement", f"{daily.sum() / plan_mtd:.1%}", f"plan {fmt_num(plan_mtd)} BCM", delta_color="off")
else:
    r[3].metric("Achievement", "—", "no plan set", delta_color="off")
if projectable:
    r[4].metric("Month-end projection", f"{fmt_num(proj)} BCM", "run rate × calendar days", delta_color="off")
else:
    r[4].metric("Days with trips", fmt_num(len(daily)))
r[5].metric("Haul distance", f"{fmt_num(weighted(ob, 'dist_h'))} m H", f"{fmt_num(weighted(ob, 'dist_v'))} m V",
            delta_color="off", help="Trip-weighted horizontal and vertical distance")

fig = go.Figure()
sh = ob.groupby(["date", "shift"])["volume"].sum().unstack(fill_value=0)
for s_, col in (("DS", T.ACCENT), ("NS", "#A8861F")):
    if s_ in sh:
        fig.add_bar(x=sh.index, y=sh[s_], name=s_, marker_color=col)
if plan.notna().any():
    fig.add_scatter(x=plan.index, y=plan.values, name="Plan", line=dict(color=T.IDLE, dash="dash"))
fig.update_layout(title="Daily OB by shift (BCM)", barmode="stack")
dash.plot(fig)

a, b = st.columns(2)
with a:
    h = ob.groupby("hour_slot")["rit"].sum().reindex(HOUR_SLOTS, fill_value=0) / max(ob["date"].nunique(), 1)
    fig = go.Figure(go.Bar(x=h.index, y=h.values, marker_color=[T.ACCENT if i < 12 else "#A8861F" for i in range(24)]))
    fig.update_layout(title="Hourly trip profile (average per day)", xaxis=dict(type="category"))
    dash.plot(fig, 340)
with b:
    dd = ob.groupby("date").apply(lambda g: pd.Series({"H": weighted(g, "dist_h"), "V": weighted(g, "dist_v")}),
                                  include_groups=False)
    fig = go.Figure()
    fig.add_scatter(x=dd.index, y=dd["H"], name="Horizontal (m)", line=dict(color=T.PA_COLOR, width=3))
    fig.add_scatter(x=dd.index, y=dd["V"], name="Vertical (m)", yaxis="y2", line=dict(color=T.ACCENT, width=3))
    fig.update_layout(title="Daily haul distance (trip-weighted)", yaxis=dict(title="horizontal (m)"),
                      yaxis2=dict(overlaying="y", side="right", title="vertical (m)"))
    dash.plot(fig, 340)

a, b, cc = st.columns(3)
with a:
    dash.ranking(ob.groupby("material")["volume"].sum().reset_index(), "material", "volume", "By material (BCM)",
                 T.ACCENT, pct=False, top=10)
with b:
    dash.ranking(ob.groupby("pit")["volume"].sum().reset_index(), "pit", "volume", "By loading location",
                 T.ACCENT, pct=False, top=12)
with cc:
    dash.ranking(ob.groupby("disposal")["volume"].sum().reset_index(), "disposal", "volume", "By disposal",
                 T.ACCENT, pct=False, top=12)

st.subheader("Haul distance by route (loading location → disposal)")
route = (ob.groupby(["pit", "disposal"]).apply(lambda g: pd.Series({
    "BCM": g["volume"].sum(), "Trips": g["rit"].sum(), "Horizontal (m)": weighted(g, "dist_h"),
    "Vertical (m)": weighted(g, "dist_v")}), include_groups=False).reset_index().sort_values("BCM", ascending=False))
route = route.rename(columns={"pit": "Loading location", "disposal": "Disposal"})
st.dataframe(route, hide_index=True, width="stretch", height=300,
             column_config={x: st.column_config.NumberColumn(format="%,.0f") for x in
                            ["BCM", "Trips", "Horizontal (m)", "Vertical (m)"]})

st.subheader("Loader × date (BCM)")
lt = ob.pivot_table(index="loader", columns="date", values="volume", aggfunc="sum", fill_value=0)
lt.columns = [f"{d:%d}" for d in lt.columns]
lt["Total"] = lt.sum(axis=1)
lt = lt.sort_values("Total", ascending=False)
st.dataframe(lt.round(0), width="stretch")
excel_download(lt.reset_index(), "ob_loader_by_date.xlsx", key="dl_lt")
cross = ob[(ob["site"] != ob["site_hauler"])]
if len(cross):
    st.caption(f"Includes {fmt_num(cross['volume'].sum())} BCM hauled by other sites' units (counted to the loader site).")
