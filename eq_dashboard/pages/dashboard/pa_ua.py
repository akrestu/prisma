"""PA & UoA per Type / Model / Unit, trend harian & mingguan, heatmap, tabel Unit × Week."""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core import dash, metrics
from core.ui import excel_download, fmt_pct

c = dash.context("pa_ua")
st.title("PA & UoA")

k = metrics.kpis(c.ev).iloc[0]
t = dash.targets(c.sites, c.month, dash.weighted_target_hours(c.ev))
r = st.columns(4)
dash.kpi(r[0], "PA", k["PA"], t["pa"], help="(Ready + Idle + Standby) / total jam")
dash.kpi(r[1], "UoA", k["UoA"], t["uoa"], help="(Ready + Idle) / (Ready + Idle + Standby)")
dash.kpi(r[2], "MA", k["MA"], help="(Ready + Idle) / (Ready + Idle + Down)")
dash.kpi(r[3], "EU", k["EU"], help="(Ready + Idle) / total jam")

metric = st.segmented_control("Metrik ranking", ["PA", "UoA", "MA"], default="PA", key="rank_metric") or "PA"
a, b, cc = st.columns(3)
with a:
    dash.ranking(metrics.kpis(c.ev, ["type"]).reset_index(), "type", metric, f"{metric} per Type", dash.COL_TYPE)
with b:
    dash.ranking(metrics.kpis(c.ev, ["model"]).reset_index(), "model", metric, f"{metric} per Model", dash.COL_MODEL)
with cc:
    worst = st.toggle("Tampilkan unit terendah", value=True)
    dash.ranking(metrics.kpis(c.ev, ["unit_id"]).reset_index(), "unit_id", metric,
                 f"{metric} per Unit ({'terendah' if worst else 'tertinggi'} 15)", dash.COL_UNIT, ascending=worst)

left, right = st.columns([2, 1])
with left:
    d = metrics.kpis(c.ev, ["date"]).reset_index()
    fig = go.Figure()
    for col, color in (("PA", "#F0A63C"), ("UoA", "#6CB6FF"), ("MA", "#30A46C")):
        fig.add_scatter(x=d["date"], y=d[col], name=col, line=dict(color=color, width=3 if col != "MA" else 2))
    if t["uoa"] is not None:
        fig.add_hline(y=t["uoa"], line_dash="dash", line_color="#93A0B2", annotation_text="target UoA")
    fig.update_layout(title="Trend harian", yaxis=dict(tickformat=".0%", range=[0, 1]))
    dash.plot(fig)
with right:
    w = metrics.kpis(c.ev, ["week"]).reset_index()
    fig = go.Figure()
    fig.add_bar(x=w["week"], y=w["PA"], name="PA", marker_color="#F0A63C", text=w["PA"].map(fmt_pct))
    fig.add_bar(x=w["week"], y=w["UoA"], name="UoA", marker_color="#6CB6FF", text=w["UoA"].map(fmt_pct))
    fig.update_layout(title="Per minggu", barmode="group", yaxis=dict(tickformat=".0%", range=[0, 1]))
    dash.plot(fig)

st.subheader("Heatmap PA per unit per hari")
hm = metrics.kpis(c.ev, ["unit_id", "date"])["PA"].unstack("date")
order = metrics.kpis(c.ev, ["unit_id"])["PA"].sort_values().index
hm = hm.reindex(order).head(60)
fig = px.imshow(hm, color_continuous_scale="RdYlGn", zmin=0, zmax=1, aspect="auto",
                labels=dict(color="PA", x="Tanggal", y="Unit"))
fig.update_layout(title=f"{len(hm)} unit dengan PA terendah")
dash.plot(fig, max(380, 16 * len(hm) + 100))

st.subheader("Unit × Week")
uw = metrics.time_buckets(c.ev, ["unit_id", "type", "model", "week"])
uw = metrics.availability(uw).reset_index()
table = uw.rename(columns={"unit_id": "Unit", "type": "Type", "model": "Model", "week": "Week",
                           "R": "Ready", "I": "Idle", "S": "Standby", "D": "Down", "T": "Total"})
table = table[["Unit", "Type", "Model", "Week", "Ready", "Idle", "Standby", "Down", "Total", "PA", "UoA", "MA"]]
st.dataframe(table, hide_index=True, width="stretch",
             column_config={x: st.column_config.NumberColumn(format="%.1f") for x in
                            ["Ready", "Idle", "Standby", "Down", "Total"]} |
             {x: st.column_config.NumberColumn(format="percent") for x in ["PA", "UoA", "MA"]})
excel_download(table, "pa_uoa_unit_week.xlsx")
