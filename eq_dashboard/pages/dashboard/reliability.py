"""Reliability: MTBS, MTTR, MTBF, Scheduled Down, PM Accuracy, Pareto komponen, bad actor, stoppage, PM."""
import pandas as pd
import plotly.express as px
import streamlit as st

from core import dash, metrics
from core.ui import excel_download, fmt_num, fmt_pct

c = dash.context("reliability")
st.title("Reliability")

rel = metrics.reliability(c.ev, c.st).iloc[0]
iv = dash.pm_intervals()
pm = metrics.pm_accuracy(c.ev, iv)
t = dash.targets(c.sites, c.month, dash.weighted_target_hours(c.ev))
r = st.columns(6)
dash.kpi(r[0], "MTBS", rel["MTBS"], t["mtbs"], "h", help="Jam kerja / jumlah stoppage (SM + USM)")
dash.kpi(r[1], "MTTR", rel["MTTR"], t["mttr"], "h", higher_better=False, help="Jam down / jumlah stoppage")
dash.kpi(r[2], "MTBF", rel["MTBF"], None, "h", help="Jam kerja / jumlah stoppage USM (breakdown)")
dash.kpi(r[3], "Scheduled Down", rel["SchedDown"], t["sched_down"], help="Jam SM / jam down")
pm_row = pm.iloc[0] if len(pm) else None
if pm_row is not None and pm_row["assessable"] > 0:
    dash.kpi(r[4], "PM Accuracy", pm_row["PMAccuracy"], t["pm_accuracy"],
             help="PM tepat interval HM ± toleransi / PM yang bisa dinilai")
else:
    r[4].metric("PM Accuracy", "—", "interval PM belum diisi" if iv.empty else "belum ada PM yang bisa dinilai",
                delta_color="off")
r[5].metric("Stoppage", fmt_num(rel["stoppages"]), f"{fmt_num(rel['usm_stoppages'])} breakdown (USM)", delta_color="off")

a, b = st.columns(2)
with a:
    dash.pareto(c.ev[c.ev["category"] == "D"], "reason_text", "hours", "Pareto jam down per komponen")
with b:
    by = st.segmented_control("Kelompok", ["type", "model"], default="type", key="rel_by",
                              format_func=lambda x: x.title()) or "type"
    rt = metrics.reliability(c.ev, c.st, [by]).reset_index()
    rt = rt[rt["stoppages"] > 0]
    fig = px.scatter(rt, x="MTBS", y="MTTR", size="down_hours", color=by, hover_name=by,
                     labels={"MTBS": "MTBS (jam)", "MTTR": "MTTR (jam)"})
    if t["mtbs"]:
        fig.add_vline(x=t["mtbs"], line_dash="dash", line_color="#93A0B2")
    if t["mttr"]:
        fig.add_hline(y=t["mttr"], line_dash="dash", line_color="#93A0B2")
    fig.update_layout(title=f"MTBS vs MTTR per {by} (kanan-bawah = baik)", showlegend=False)
    dash.plot(fig, 380)

st.subheader("Bad actor: unit dengan jam down terbesar")
bad = (c.st.groupby(["unit_id", "type", "model"], dropna=False)
       .agg(stoppage=("hours", "size"), jam_down=("hours", "sum"), jam_usm=("usm_hours", "sum"),
            jam_sm=("sm_hours", "sum")).reset_index().sort_values("jam_down", ascending=False).head(20))
main = (c.ev[c.ev["category"] == "D"].groupby(["unit_id", "reason_text"])["hours"].sum().reset_index()
        .sort_values("hours", ascending=False).drop_duplicates("unit_id").set_index("unit_id")["reason_text"])
bad["komponen_utama"] = bad["unit_id"].map(main)
st.dataframe(bad, hide_index=True, width="stretch",
             column_config={x: st.column_config.NumberColumn(format="%.1f") for x in ["jam_down", "jam_usm", "jam_sm"]})

st.subheader("Daftar stoppage")
stp = c.st.sort_values(["start_date", "unit_id"]).rename(columns={
    "unit_id": "Unit", "type": "Type", "model": "Model", "start_date": "Mulai", "start_shift": "Shift",
    "end_date": "Selesai", "hours": "Jam", "sm_hours": "Jam SM", "usm_hours": "Jam USM", "main_reason": "Komponen"})
st.dataframe(stp[["Unit", "Type", "Model", "Mulai", "Shift", "Selesai", "Jam", "Jam SM", "Jam USM", "Komponen"]],
             hide_index=True, width="stretch", height=320)
excel_download(stp, "stoppage.xlsx", key="dl_stp")

st.subheader("Riwayat PM (reason 502)")
p = c.ev[c.ev["reason_code"] == 502].sort_values(["unit_id", "seq"])
p = p[p["seq"] - p.groupby("unit_id")["seq"].shift() != 1]
p = p.assign(hm_sebelumnya=p.groupby("unit_id")["hm_start"].shift(),
             selisih_hm=lambda d: d["hm_start"] - d["hm_sebelumnya"]).merge(iv, on="model", how="left")
st.dataframe(p[["unit_id", "model", "date", "shift", "hm_start", "hm_sebelumnya", "selisih_hm", "interval_hm",
                "tolerance_pct"]], hide_index=True, width="stretch", height=300)
if iv.empty:
    st.info("Isi interval PM per model di halaman **Interval PM & Standby** untuk menghitung PM Accuracy.")
