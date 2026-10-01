"""Reliability: MTBS, MTTR, MTBF, scheduled down, PM accuracy, component Pareto, bad actors, stoppages, PM."""
import plotly.express as px
import streamlit as st

from core import dash, metrics
from core import theme as T
from core.ui import excel_download, fmt_num

c = dash.context("reliability", title="Reliability")
st.title("Reliability")

rel = metrics.reliability(c.ev, c.st).iloc[0]
iv = dash.pm_intervals()
pm = metrics.pm_accuracy(c.ev, iv)
t = dash.targets_for(c)
pv = dash.headline(c.prev)
comp = c.ev[c.ev["category"] == "D"].groupby("reason_text")["hours"].sum().sort_values(ascending=False)
dash.summary(dash.gap_text("MTBS", rel["MTBS"], t["mtbs"], "hrs"),
             dash.gap_text("MTTR", rel["MTTR"], t["mttr"], "hrs", higher_better=False),
             f"{str(comp.index[0]).capitalize()} is the largest down cause ({comp.iloc[0] / comp.sum():.0%})" if len(comp) else "")
r = st.columns(6)
dash.kpi(r[0], "MTBS (hrs)", rel["MTBS"], t["mtbs"], "h", help="Working hours / number of stoppages (SM + USM)", prev=pv.get("MTBS"))
dash.kpi(r[1], "MTTR (hrs)", rel["MTTR"], t["mttr"], "h", higher_better=False, help="Down hours / number of stoppages", prev=pv.get("MTTR"))
dash.kpi(r[2], "MTBF (hrs)", rel["MTBF"], None, "h", help="Working hours / number of USM (breakdown) stoppages", prev=pv.get("MTBF"))
dash.kpi(r[3], "Scheduled down (%)", rel["SchedDown"], t["sched_down"], help="SM hours / down hours", prev=pv.get("SchedDown"))
pm_row = pm.iloc[0] if len(pm) else None
if pm_row is not None and pm_row["assessable"] > 0:
    dash.kpi(r[4], "PM accuracy (%)", pm_row["PMAccuracy"], t["pm_accuracy"],
             help="PMs within HM interval ± tolerance / assessable PMs")
else:
    r[4].metric("PM accuracy", "—", "PM intervals not set" if iv.empty else "no assessable PM yet", delta_color="off")
r[5].metric("Stoppages", fmt_num(rel["stoppages"]), f"{fmt_num(rel['usm_stoppages'])} breakdowns (USM)",
            delta_color="off")

a, b = st.columns(2)
with a:
    dash.pareto(c.ev[c.ev["category"] == "D"], "reason_text", "hours", "Down hours Pareto by component")
with b:
    by = st.segmented_control("Group by", ["type", "model"], default="type", key="rel_by",
                              format_func=lambda x: x.title()) or "type"
    rt = metrics.reliability(c.ev, c.st, [by]).reset_index()
    rt = rt[rt["stoppages"] > 0]
    fig = px.scatter(rt, x="MTBS", y="MTTR", size="down_hours", color=by, hover_name=by,
                     labels={"MTBS": "MTBS (hrs)", "MTTR": "MTTR (hrs)"})
    if t["mtbs"]:
        fig.add_vline(x=t["mtbs"], line_dash="dash", line_color=T.ACCENT)
    if t["mttr"]:
        fig.add_hline(y=t["mttr"], line_dash="dash", line_color=T.ACCENT)
    fig.update_layout(title=f"MTBS vs MTTR by {by} (bottom-right is better)", showlegend=False)
    dash.plot(fig, 380)

st.subheader("Bad actors: units with the most down hours")
bad = (c.st.groupby(["unit_id", "type", "model"], dropna=False)
       .agg(stoppages=("hours", "size"), down_h=("hours", "sum"), usm_h=("usm_hours", "sum"),
            sm_h=("sm_hours", "sum")).reset_index().sort_values("down_h", ascending=False).head(20))
main = (c.ev[c.ev["category"] == "D"].groupby(["unit_id", "reason_text"])["hours"].sum().reset_index()
        .sort_values("hours", ascending=False).drop_duplicates("unit_id").set_index("unit_id")["reason_text"])
bad["main_component"] = bad["unit_id"].map(main)
st.dataframe(bad, hide_index=True, width="stretch",
             column_config={x: st.column_config.NumberColumn(format="%.1f") for x in ["down_h", "usm_h", "sm_h"]})

st.subheader("Stoppage list")
stp = c.st.sort_values(["start_date", "unit_id"]).rename(columns={
    "unit_id": "Unit", "type": "Type", "model": "Model", "start_date": "Start", "start_shift": "Shift",
    "end_date": "End", "hours": "Hours", "sm_hours": "SM h", "usm_hours": "USM h", "main_reason": "Component"})
st.dataframe(stp[["Unit", "Type", "Model", "Start", "Shift", "End", "Hours", "SM h", "USM h", "Component"]],
             hide_index=True, width="stretch", height=320)
excel_download(stp, "stoppages.xlsx", key="dl_stp")

st.subheader("PM history (reason 502)")
p = c.ev[c.ev["reason_code"] == 502].sort_values(["unit_id", "seq"])
p = p[p["seq"] - p.groupby("unit_id")["seq"].shift() != 1]
p = p.assign(prev_hm=p.groupby("unit_id")["hm_start"].shift(),
             hm_gap=lambda d: d["hm_start"] - d["prev_hm"]).merge(iv, on="model", how="left")
st.dataframe(p[["unit_id", "model", "date", "shift", "hm_start", "prev_hm", "hm_gap", "interval_hm", "tolerance_pct"]],
             hide_index=True, width="stretch", height=300)
if iv.empty:
    st.info("Set PM intervals per model on the **PM intervals & standby** page to calculate PM accuracy.")
