"""Overview: KPIs vs target, trends, production, site comparison."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import dash, metrics
from core.ui import fmt_num, fmt_pct

c = dash.context("overview")
st.title("Overview")

k = metrics.kpis(c.ev).iloc[0]
rel = metrics.reliability(c.ev, c.st).iloc[0]
t = dash.targets(c.sites, c.month, dash.weighted_target_hours(c.ev))
ob = c.rit.loc[c.rit["material_group"] == "OB", "volume"].sum() if len(c.rit) else 0
coal = c.coal["ton"].sum() if len(c.coal) else 0
fuel = c.fuel["liters"].sum() if len(c.fuel) else 0

r1 = st.columns(4)
dash.kpi(r1[0], "PA", k["PA"], t["pa"])
dash.kpi(r1[1], "UoA", k["UoA"], t["uoa"])
dash.kpi(r1[2], "MTBS", rel["MTBS"], t["mtbs"], "h")
dash.kpi(r1[3], "MTTR", rel["MTTR"], t["mttr"], "h", higher_better=False)
r2 = st.columns(4)
plan = dash.plan_daily(tuple(c.sites), c.month)
plan = plan[(plan["date"] >= c.date_from) & (plan["date"] <= c.date_to)]
dash.kpi(r2[0], "OB (BCM)", ob, plan["ob_plan"].sum(min_count=1), "n")
dash.kpi(r2[1], "Coal (t)", coal, plan["coal_plan"].sum(min_count=1), "n1")
dash.kpi(r2[2], "Fuel (L)", fuel, None, "n")
r2[3].metric("Fuel ratio", f"{fmt_num(fuel / ob, 2)} L/BCM" if ob else "—")

left, right = st.columns(2)
with left:
    d = metrics.kpis(c.ev, ["date"]).reset_index()
    fig = go.Figure()
    fig.add_scatter(x=d["date"], y=d["PA"], name="PA", line=dict(color="#F0A63C", width=3))
    fig.add_scatter(x=d["date"], y=d["UoA"], name="UoA", line=dict(color="#6CB6FF", width=3))
    if t["uoa"] is not None:
        fig.add_hline(y=t["uoa"], line_dash="dash", line_color="#93A0B2", annotation_text="UoA target")
    if t["pa"] is not None:
        fig.add_hline(y=t["pa"], line_dash="dot", line_color="#F0A63C", annotation_text="PA target")
    fig.update_layout(title="Daily PA & UoA", yaxis=dict(tickformat=".0%", range=[0, 1]))
    dash.plot(fig)
with right:
    fig = go.Figure()
    if len(c.rit):
        o = c.rit[c.rit["material_group"] == "OB"].groupby("date")["volume"].sum()
        fig.add_bar(x=o.index, y=o.values, name="OB (BCM)", marker_color="#F0A63C")
    if len(c.coal):
        cc = c.coal.groupby("date")["ton"].sum()
        fig.add_scatter(x=cc.index, y=cc.values, name="Coal (t)", yaxis="y2", line=dict(color="#6CB6FF", width=3))
    if plan["ob_plan"].notna().any():
        fig.add_scatter(x=plan["date"], y=plan["ob_plan"], name="OB plan", line=dict(color="#E8ECF1", dash="dash"))
    fig.update_layout(title="Daily production", yaxis2=dict(overlaying="y", side="right", title="t"))
    dash.plot(fig)

st.subheader("By site")
b = metrics.availability(metrics.time_buckets(c.ev, ["site"]))
rs = metrics.reliability(c.ev, c.st, ["site"])
obs = c.rit[c.rit["material_group"] == "OB"].groupby("site")["volume"].sum() if len(c.rit) else pd.Series(dtype=float)
cs = c.coal.groupby("site")["ton"].sum() if len(c.coal) else pd.Series(dtype=float)
fs = c.fuel.groupby("site")["liters"].sum() if len(c.fuel) else pd.Series(dtype=float)
tab = pd.DataFrame({"PA": b["PA"].map(fmt_pct), "UoA": b["UoA"].map(fmt_pct), "MA": b["MA"].map(fmt_pct),
                    "MTBS (h)": rs["MTBS"].map(lambda v: fmt_num(v, 1)),
                    "MTTR (h)": rs["MTTR"].map(lambda v: fmt_num(v, 1)),
                    "OB (BCM)": obs.reindex(b.index).map(fmt_num), "Coal (t)": cs.reindex(b.index).map(fmt_num),
                    "Fuel (L)": fs.reindex(b.index).map(fmt_num)})
st.dataframe(tab, width="stretch")

st.subheader("By type")
bt = metrics.availability(metrics.time_buckets(c.ev, ["type"]))
st.dataframe(pd.DataFrame({"Ready h": bt["R"].round(0), "Idle h": bt["I"].round(0), "Standby h": bt["S"].round(0),
                           "Down h": bt["D"].round(0), "PA": bt["PA"].map(fmt_pct), "UoA": bt["UoA"].map(fmt_pct),
                           "MA": bt["MA"].map(fmt_pct)}), width="stretch")
