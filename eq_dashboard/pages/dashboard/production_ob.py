"""Produksi OB dari ritase: BCM harian vs plan, profil per jam, material, pit, disposal, hauler."""
import calendar

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import dash
from core.ui import excel_download, fmt_num

c = dash.context("production_ob", unit_filter=False)
st.title("Produksi OB")
ob = c.rit[c.rit["material_group"] == "OB"] if len(c.rit) else c.rit
if ob.empty:
    st.info("Tidak ada data ritase OB untuk pilihan ini.")
    st.stop()

daily = ob.groupby("date")["volume"].sum()
plan = dash.plan_daily(tuple(c.sites), c.month).set_index("date")["ob_plan"]
plan_mtd = plan.reindex(daily.index).sum(min_count=1)
days_in_month = calendar.monthrange(c.month.year, c.month.month)[1]
proj = daily.mean() * days_in_month
r = st.columns(5)
r[0].metric("OB MTD", f"{fmt_num(daily.sum())} BCM")
r[1].metric("Rata-rata / hari", f"{fmt_num(daily.mean())} BCM")
r[2].metric("Ritase", fmt_num(ob["rit"].sum()))
if pd.notna(plan_mtd) and plan_mtd:
    r[3].metric("Achievement MTD", f"{daily.sum() / plan_mtd:.1%}".replace(".", ","), f"plan {fmt_num(plan_mtd)} BCM",
                delta_color="off")
else:
    r[3].metric("Achievement MTD", "—", "plan belum diisi", delta_color="off")
r[4].metric("Proyeksi akhir bulan", f"{fmt_num(proj)} BCM", "run-rate × hari kalender", delta_color="off")

fig = go.Figure()
sh = ob.groupby(["date", "shift"])["volume"].sum().unstack(fill_value=0)
for s_, col in (("DS", "#F0A63C"), ("NS", "#B7791F")):
    if s_ in sh:
        fig.add_bar(x=sh.index, y=sh[s_], name=s_, marker_color=col)
if plan.notna().any():
    fig.add_scatter(x=plan.index, y=plan.values, name="Plan", line=dict(color="#E8ECF1", dash="dash"))
fig.update_layout(title="OB harian per shift (BCM)", barmode="stack")
dash.plot(fig)

a, b = st.columns(2)
with a:
    from core.validate import HOUR_SLOTS
    h = ob.groupby("hour_slot")["rit"].sum().reindex(HOUR_SLOTS, fill_value=0) / max(ob["date"].nunique(), 1)
    fig = go.Figure(go.Bar(x=h.index, y=h.values, marker_color=["#F0A63C" if i < 12 else "#B7791F" for i in range(24)]))
    fig.update_layout(title="Profil ritase per jam (rata-rata per hari)", xaxis=dict(type="category"))
    dash.plot(fig, 340)
with b:
    m_ = ob.groupby("material")["volume"].sum().reset_index()
    dash.ranking(m_, "material", "volume", "OB per material (BCM)", "#F0A63C", pct=False, height=340)

a, b, cc = st.columns(3)
with a:
    dash.ranking(ob.groupby("pit")["volume"].sum().reset_index(), "pit", "volume", "Per lokasi loader", dash.COL_TYPE,
                 pct=False, top=12)
with b:
    dash.ranking(ob.groupby("disposal")["volume"].sum().reset_index(), "disposal", "volume", "Per disposal",
                 dash.COL_MODEL, pct=False, top=12)
with cc:
    dash.ranking(ob.groupby("hauler_model")["volume"].sum().reset_index(), "hauler_model", "volume",
                 "Per model hauler", dash.COL_UNIT, pct=False, top=12)

st.subheader("Loader × tanggal (BCM)")
lt = ob.pivot_table(index="loader", columns="date", values="volume", aggfunc="sum", fill_value=0)
lt.columns = [f"{d:%d}" for d in lt.columns]
lt["Total"] = lt.sum(axis=1)
lt = lt.sort_values("Total", ascending=False)
st.dataframe(lt.round(0), width="stretch")
excel_download(lt.reset_index(), "ob_loader_tanggal.xlsx", key="dl_lt")
cross = ob[(ob["site"] != ob["site_hauler"])]
if len(cross):
    st.caption(f"Termasuk {fmt_num(cross['volume'].sum())} BCM dari hauler site lain (dicatat ke site loader).")
