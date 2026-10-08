"""Overview: KPIs vs target, trends, production, site comparison."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import dash, metrics
from core import theme as T
from core.ui import fmt_num, fmt_pct

c = dash.context("overview", title="Overview")
st.title("Overview")
st.caption("The month at a glance per site: production, equipment availability and fuel.")

k = metrics.kpis(c.ev).iloc[0]
rel = metrics.reliability(c.ev, c.st).iloc[0]
t = dash.targets_for(c)
pv = dash.headline(c.prev)
ob = c.rit.loc[c.rit["material_group"] == "OB", "volume"].sum() if len(c.rit) else 0
coal = c.coal["ton"].sum() if len(c.coal) else 0
fuel = c.fuel["liters"].sum() if len(c.fuel) else 0
top_down = (c.ev[c.ev["category"] == "D"].groupby("reason_text")["hours"].sum().sort_values(ascending=False)
            if len(c.ev) else None)
dash.summary(dash.gap_text("UoA", k["UoA"], t["uoa"]), dash.gap_text("PA", k["PA"], t["pa"]),
             f"{str(top_down.index[0]).capitalize()} causes {top_down.iloc[0] / top_down.sum():.0%} of down hours"
             if top_down is not None and len(top_down) else "",
             f"OB {fmt_num(ob)} BCM and coal {fmt_num(coal)} t in the selected dates")

r1 = st.columns(4)
dash.kpi(r1[0], "PA (%)", k["PA"], t["pa"], prev=pv.get("PA"))
dash.kpi(r1[1], "UoA (%)", k["UoA"], t["uoa"], prev=pv.get("UoA"))
dash.kpi(r1[2], "MTBS (hrs)", rel["MTBS"], t["mtbs"], "h", prev=pv.get("MTBS"))
dash.kpi(r1[3], "MTTR (hrs)", rel["MTTR"], t["mttr"], "h", higher_better=False, prev=pv.get("MTTR"))
r2 = st.columns(4)
plan = dash.plan_range(c.sites, c.date_from, c.date_to)
dash.kpi(r2[0], "OB (BCM)", ob, plan["ob_plan"].sum(min_count=1), "n", prev=pv.get("OB"))
dash.kpi(r2[1], "Coal (t)", coal, plan["coal_plan"].sum(min_count=1), "n1", prev=pv.get("coal"))
dash.kpi(r2[2], "Fuel (L)", fuel, None, "n", higher_better=False, prev=pv.get("fuel"))
r2[3].metric("Fuel ratio", f"{fmt_num(fuel / ob, 2)} L/BCM" if ob else "—")

left, right = st.columns(2)
with left:
    d = metrics.kpis(c.ev, ["date"]).reset_index()
    fig = go.Figure()
    fig.add_scatter(x=d["date"], y=d["PA"], name="PA", line=dict(color=T.PA_COLOR, width=3))
    fig.add_scatter(x=d["date"], y=d["UoA"], name="UoA", line=dict(color=T.READY, width=3))
    if t["uoa"] is not None:
        fig.add_hline(y=t["uoa"], line_dash="dot", line_color=T.ACCENT, annotation_text="UoA target")
    if t["pa"] is not None:
        fig.add_hline(y=t["pa"], line_dash="dot", line_color=T.PA_COLOR, annotation_text="PA target")
    fig.update_layout(title="Daily PA & UoA", yaxis=dict(tickformat=".0%", range=[0, 1]))
    dash.plot(fig)
with right:
    fig = go.Figure()
    if len(c.rit):
        o = c.rit[c.rit["material_group"] == "OB"].groupby("date")["volume"].sum()
        fig.add_bar(x=o.index, y=o.values, name="OB (BCM)", marker_color=T.ACCENT)
    if len(c.coal):
        cc = c.coal.groupby("date")["ton"].sum()
        fig.add_scatter(x=cc.index, y=cc.values, name="Coal (t)", yaxis="y2", line=dict(color=T.READY, width=3))
    if plan["ob_plan"].notna().any():
        fig.add_scatter(x=plan["date"], y=plan["ob_plan"], name="OB plan", line=dict(color=T.IDLE, dash="dash"))
    fig.update_layout(title="Daily production", yaxis2=dict(overlaying="y", side="right", title="t"))
    dash.plot(fig)

st.subheader("By site")
b = metrics.availability(metrics.time_buckets(c.ev, ["site"]))
rs = metrics.reliability(c.ev, c.st, ["site"])
obs = c.rit[c.rit["material_group"] == "OB"].groupby("site")["volume"].sum() if len(c.rit) else pd.Series(dtype=float)
cs = c.coal.groupby("site")["ton"].sum() if len(c.coal) else pd.Series(dtype=float)
fs = c.fuel.groupby("site")["liters"].sum() if len(c.fuel) else pd.Series(dtype=float)
tab = pd.DataFrame({"PA": b["PA"].map(fmt_pct), "UoA": b["UoA"].map(fmt_pct), "MA": b["MA"].map(fmt_pct),
                    "MTBS (hrs)": rs["MTBS"].map(lambda v: fmt_num(v, 1)),
                    "MTTR (hrs)": rs["MTTR"].map(lambda v: fmt_num(v, 1)),
                    "OB (BCM)": obs.reindex(b.index).map(fmt_num), "Coal (t)": cs.reindex(b.index).map(fmt_num),
                    "Fuel (L)": fs.reindex(b.index).map(fmt_num)})
st.dataframe(tab, width="stretch")

st.subheader("By type")
bt = metrics.availability(metrics.time_buckets(c.ev, ["type"]))
st.dataframe(pd.DataFrame({"Ready h": bt["R"].round(0), "Idle h": bt["I"].round(0), "Standby h": bt["S"].round(0),
                           "Down h": bt["D"].round(0), "PA": bt["PA"].map(fmt_pct), "UoA": bt["UoA"].map(fmt_pct),
                           "MA": bt["MA"].map(fmt_pct)}), width="stretch")
