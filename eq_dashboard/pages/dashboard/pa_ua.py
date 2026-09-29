"""PA & UoA by Type / Model / Unit, daily & weekly trends, heatmap, Unit × Week table."""
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core import dash, metrics
from core import theme as T
from core.ui import excel_download, fmt_pct

c = dash.context("pa_ua")
st.title("PA & UoA")

k = metrics.kpis(c.ev).iloc[0]
t = dash.targets_for(c)
pv = dash.headline(c.prev)
worst_type = metrics.kpis(c.ev, ["type"])["PA"].sort_values()
dash.summary(dash.gap_text("UoA", k["UoA"], t["uoa"]), dash.gap_text("PA", k["PA"], t["pa"]),
             f"Lowest PA by type: {worst_type.index[0]} at {worst_type.iloc[0]:.0%}" if len(worst_type) else "")
r = st.columns(4)
dash.kpi(r[0], "PA (%)", k["PA"], t["pa"], help="(Ready + Idle + Standby) / total hours", prev=pv.get("PA"))
dash.kpi(r[1], "UoA (%)", k["UoA"], t["uoa"], help="(Ready + Idle) / (Ready + Idle + Standby)", prev=pv.get("UoA"))
dash.kpi(r[2], "MA (%)", k["MA"], help="(Ready + Idle) / (Ready + Idle + Down)", prev=pv.get("MA"))
dash.kpi(r[3], "EU (%)", k["EU"], help="(Ready + Idle) / total hours", prev=pv.get("EU"))

metric = st.segmented_control("Ranking metric", ["PA", "UoA", "MA"], default="PA", key="rank_metric") or "PA"
a, b, cc = st.columns(3)
with a:
    dash.ranking(metrics.kpis(c.ev, ["type"]).reset_index(), "type", metric, f"{metric} by type", T.METRIC_COLOR[metric])
with b:
    dash.ranking(metrics.kpis(c.ev, ["model"]).reset_index(), "model", metric, f"{metric} by model", T.METRIC_COLOR[metric])
with cc:
    worst = st.toggle("Show lowest units", value=True)
    dash.ranking(metrics.kpis(c.ev, ["unit_id"]).reset_index(), "unit_id", metric,
                 f"{metric} by unit ({'lowest' if worst else 'highest'} 15)", T.METRIC_COLOR[metric], ascending=worst)

left, right = st.columns([2, 1])
with left:
    d = metrics.kpis(c.ev, ["date"]).reset_index()
    fig = go.Figure()
    for col, color in (("PA", T.PA_COLOR), ("UoA", T.READY), ("MA", T.IDLE)):
        fig.add_scatter(x=d["date"], y=d[col], name=col, line=dict(color=color, width=3 if col != "MA" else 2))
    if t["uoa"] is not None:
        fig.add_hline(y=t["uoa"], line_dash="dot", line_color=T.ACCENT, annotation_text="UoA target")
    fig.update_layout(title="Daily trend", yaxis=dict(tickformat=".0%", range=[0, 1]))
    dash.plot(fig)
with right:
    w = metrics.kpis(c.ev, ["week"]).reset_index()
    fig = go.Figure()
    fig.add_bar(x=w["week"], y=w["PA"], name="PA", marker_color=T.PA_COLOR, text=w["PA"].map(fmt_pct))
    fig.add_bar(x=w["week"], y=w["UoA"], name="UoA", marker_color=T.READY, text=w["UoA"].map(fmt_pct))
    fig.update_layout(title="By week", barmode="group", yaxis=dict(tickformat=".0%", range=[0, 1]))
    dash.plot(fig)

st.subheader("PA heatmap by unit and day")
hm = metrics.kpis(c.ev, ["unit_id", "date"])["PA"].unstack("date")
order = metrics.kpis(c.ev, ["unit_id"])["PA"].sort_values().index
hm = hm.reindex(order).head(60)
fig = px.imshow(hm, color_continuous_scale=[T.MISS, T.ACCENT, T.READY], zmin=0, zmax=1, aspect="auto",
                labels=dict(color="PA", x="Date", y="Unit"))
fig.update_layout(title=f"{len(hm)} units with the lowest PA")
dash.plot(fig, max(380, 16 * len(hm) + 100))

st.subheader("Unit × week")
uw = metrics.availability(metrics.time_buckets(c.ev, ["unit_id", "type", "model", "week"])).reset_index()
table = uw.rename(columns={"unit_id": "Unit", "type": "Type", "model": "Model", "week": "Week",
                           "R": "Ready", "I": "Idle", "S": "Standby", "D": "Down", "T": "Total"})
table = table[["Unit", "Type", "Model", "Week", "Ready", "Idle", "Standby", "Down", "Total", "PA", "UoA", "MA"]]
for col in ("PA", "UoA", "MA"):
    table[col] = table[col].map(fmt_pct)
st.dataframe(table, hide_index=True, width="stretch",
             column_config={x: st.column_config.NumberColumn(format="%.1f") for x in
                            ["Ready", "Idle", "Standby", "Down", "Total"]})
excel_download(table, "pa_uoa_unit_week.xlsx")
