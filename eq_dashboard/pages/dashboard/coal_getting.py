"""Coal getting dari timbangan: ton harian vs plan, per seam/loader/DT, cross-check ritase CG."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import dash
from core.ui import excel_download, fmt_num

c = dash.context("coal_getting", unit_filter=False)
st.title("Coal getting")
t = c.coal
if t.empty:
    st.info("Tidak ada data timbangan untuk pilihan ini.")
    st.stop()

daily = t.groupby("date")["ton"].sum()
plan = dash.plan_daily(tuple(c.sites), c.month).set_index("date")["coal_plan"]
plan_mtd = plan.reindex(daily.index).sum(min_count=1)
r = st.columns(5)
r[0].metric("Coal MTD", f"{fmt_num(daily.sum(), 1)} t")
r[1].metric("Tiket", fmt_num(len(t)))
r[2].metric("Payload rata-rata DT", f"{fmt_num(t['ton'].mean(), 2)} t")
dur = (pd.to_datetime(t["time_out"]) - pd.to_datetime(t["time_in"])).dt.total_seconds() / 60
r[3].metric("Durasi masuk–keluar (median)", f"{fmt_num(dur.median(), 1)} mnt")
if pd.notna(plan_mtd) and plan_mtd:
    r[4].metric("Achievement MTD", f"{daily.sum() / plan_mtd:.1%}".replace(".", ","), f"plan {fmt_num(plan_mtd)} t",
                delta_color="off")
else:
    r[4].metric("Achievement MTD", "—", "plan belum diisi", delta_color="off")

fig = go.Figure()
sh = t.groupby(["date", "shift"])["ton"].sum().unstack(fill_value=0)
for s_, col in (("DS", "#6CB6FF"), ("NS", "#2F6DB5")):
    if s_ in sh:
        fig.add_bar(x=sh.index, y=sh[s_], name=s_, marker_color=col)
if plan.notna().any():
    fig.add_scatter(x=plan.index, y=plan.values, name="Plan", line=dict(color="#E8ECF1", dash="dash"))
cg = c.rit[c.rit["material_group"] == "CG"].groupby("date")["volume"].sum() if len(c.rit) else pd.Series(dtype=float)
if len(cg):
    fig.add_scatter(x=cg.index, y=cg.values, name="Ritase CG (ton, estimasi)", line=dict(color="#F5B400", dash="dot"))
fig.update_layout(title="Coal harian (timbangan) vs ritase CG", barmode="stack")
dash.plot(fig)
if len(cg):
    st.caption(f"Ritase CG × Muatan: {fmt_num(cg.sum(), 0)} t vs timbangan {fmt_num(daily.sum(), 0)} t "
               f"(selisih {fmt_num(cg.sum() - daily.sum(), 0)} t). Angka resmi memakai timbangan.")

a, b, cc = st.columns(3)
with a:
    dash.ranking(t.groupby("seam", dropna=False)["ton"].sum().reset_index().fillna({"seam": "—"}), "seam", "ton",
                 "Per seam (t)", dash.COL_TYPE, pct=False, top=10)
with b:
    dash.ranking(t.groupby("loader", dropna=False)["ton"].sum().reset_index().fillna({"loader": "—"}), "loader",
                 "ton", "Per loader (t)", dash.COL_MODEL, pct=False, top=12)
with cc:
    dash.ranking(t.groupby("dt_unit")["ton"].sum().reset_index(), "dt_unit", "ton", "Per DT (t, 15 teratas)",
                 dash.COL_UNIT, pct=False, top=15)

st.subheader("Rekap per DT")
rec = (t.assign(dur=dur).groupby("dt_unit")
       .agg(ritase=("ton", "size"), ton=("ton", "sum"), payload=("ton", "mean"), durasi_median=("dur", "median"))
       .reset_index().sort_values("ton", ascending=False))
st.dataframe(rec, hide_index=True, width="stretch",
             column_config={"ton": st.column_config.NumberColumn(format="%.1f"),
                            "payload": st.column_config.NumberColumn(format="%.2f"),
                            "durasi_median": st.column_config.NumberColumn("durasi median (mnt)", format="%.1f")})
excel_download(rec, "coal_per_dt.xlsx")
