"""Coal getting from the weighbridge: daily tonnes vs plan, seam/loader/DT, CG ritase cross-check, haul distance."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import dash
from core import theme as T
from core.periods import weighted
from core.ui import excel_download, fmt_num

c = dash.context("coal_getting", unit_filter=False, title="Coal getting")
st.title("Coal getting")
t = c.coal
if t.empty:
    st.info("No weighbridge data for this selection.")
    st.stop()

cg = c.rit[c.rit["material_group"] == "CG"] if len(c.rit) else c.rit
daily = t.groupby("date")["ton"].sum()
plan = dash.plan_range(c.sites, c.date_from, c.date_to).set_index("date")["coal_plan"]
plan_mtd = plan.reindex(daily.index).sum(min_count=1)
dur = (pd.to_datetime(t["time_out"]) - pd.to_datetime(t["time_in"])).dt.total_seconds() / 60
top_seam = t.groupby("seam")["ton"].sum().sort_values(ascending=False)
dash.summary(f"{fmt_num(daily.sum(), 1)} t from {fmt_num(len(t))} weighbridge tickets, average payload {fmt_num(t['ton'].mean(), 1)} t",
             f"{top_seam.index[0]} gives {top_seam.iloc[0] / top_seam.sum():.0%} of coal" if len(top_seam) else "")
r = st.columns(6)
r[0].metric("Coal in period", f"{fmt_num(daily.sum(), 1)} t")
r[1].metric("Tickets", fmt_num(len(t)))
r[2].metric("Average DT payload", f"{fmt_num(t['ton'].mean(), 2)} t")
r[3].metric("Median in–out time", f"{fmt_num(dur.median(), 1)} min")
if pd.notna(plan_mtd) and plan_mtd:
    r[4].metric("Achievement", f"{daily.sum() / plan_mtd:.1%}", f"plan {fmt_num(plan_mtd)} t", delta_color="off")
else:
    r[4].metric("Achievement", "—", "no plan set", delta_color="off")
if len(cg):
    r[5].metric("CG haul distance", f"{fmt_num(weighted(cg, 'dist_h'))} m H", f"{fmt_num(weighted(cg, 'dist_v'))} m V",
                delta_color="off", help="Trip-weighted, from CG ritase")

fig = go.Figure()
sh = t.groupby(["date", "shift"])["ton"].sum().unstack(fill_value=0)
for s_, col in (("DS", T.READY), ("NS", "#2F6497")):
    if s_ in sh:
        fig.add_bar(x=sh.index, y=sh[s_], name=s_, marker_color=col)
if plan.notna().any():
    fig.add_scatter(x=plan.index, y=plan.values, name="Plan", line=dict(color=T.ACCENT, dash="dash"))
cgd = cg.groupby("date")["volume"].sum() if len(cg) else pd.Series(dtype=float)
if len(cgd):
    fig.add_scatter(x=cgd.index, y=cgd.values, name="CG ritase (t, estimate)", line=dict(color=T.ACCENT, dash="dot"))
fig.update_layout(title="Daily coal (weighbridge) vs CG ritase", barmode="stack")
dash.plot(fig)
if len(cgd):
    st.caption(f"CG ritase × Muatan: {fmt_num(cgd.sum())} t vs weighbridge {fmt_num(daily.sum())} t "
               f"(difference {fmt_num(cgd.sum() - daily.sum())} t). Official figures use the weighbridge.")

if len(cg):
    a, b = st.columns(2)
    with a:
        dd = cg.groupby("date").apply(lambda g: pd.Series({"H": weighted(g, "dist_h"), "V": weighted(g, "dist_v")}),
                                      include_groups=False)
        fig = go.Figure()
        fig.add_scatter(x=dd.index, y=dd["H"], name="Horizontal (m)", line=dict(color=T.PA_COLOR, width=3))
        fig.add_scatter(x=dd.index, y=dd["V"], name="Vertical (m)", yaxis="y2", line=dict(color=T.ACCENT, width=3))
        fig.update_layout(title="Daily CG haul distance (trip-weighted)", yaxis=dict(title="horizontal (m)"),
                          yaxis2=dict(overlaying="y", side="right", title="vertical (m)"))
        dash.plot(fig, 340)
    with b:
        route = (cg.groupby(["pit", "disposal"]).apply(lambda g: pd.Series({
            "t (ritase)": g["volume"].sum(), "Trips": g["rit"].sum(), "Horizontal (m)": weighted(g, "dist_h"),
            "Vertical (m)": weighted(g, "dist_v")}), include_groups=False).reset_index()
            .sort_values("t (ritase)", ascending=False).rename(columns={"pit": "Loading location", "disposal": "Destination"}))
        st.markdown("**CG routes**")
        st.dataframe(route, hide_index=True, width="stretch", height=300,
                     column_config={x: st.column_config.NumberColumn(format="%,.0f") for x in
                                    ["t (ritase)", "Trips", "Horizontal (m)", "Vertical (m)"]})

a, b, cc = st.columns(3)
with a:
    dash.ranking(t.groupby("seam", dropna=False)["ton"].sum().reset_index().fillna({"seam": "—"}), "seam", "ton",
                 "By seam (t)", T.READY, pct=False, top=10)
with b:
    dash.ranking(t.groupby("loader", dropna=False)["ton"].sum().reset_index().fillna({"loader": "—"}), "loader",
                 "ton", "By loader (t)", T.READY, pct=False, top=12)
with cc:
    dash.ranking(t.groupby("dt_unit")["ton"].sum().reset_index(), "dt_unit", "ton", "By DT (t, top 15)",
                 T.READY, pct=False, top=15)

st.subheader("By dump truck")
rec = (t.assign(dur=dur).groupby("dt_unit")
       .agg(trips=("ton", "size"), tonnes=("ton", "sum"), payload=("ton", "mean"), median_min=("dur", "median"))
       .reset_index().sort_values("tonnes", ascending=False))
st.dataframe(rec, hide_index=True, width="stretch",
             column_config={"tonnes": st.column_config.NumberColumn(format="%,.1f"),
                            "payload": st.column_config.NumberColumn(format="%.2f"),
                            "median_min": st.column_config.NumberColumn("median in–out (min)", format="%.1f")})
excel_download(rec, "coal_by_dt.xlsx")
