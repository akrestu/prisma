"""Fuel: consume vs receipt, fuel ratio per site & fleet, liter per Type/Model/Unit, L/jam HM, outlier."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import dash
from core.ui import excel_download, fmt_num

c = dash.context("fuel")
st.title("Fuel")
f = c.fuel
if f.empty:
    st.info("Tidak ada data fuel untuk pilihan ini.")
    st.stop()

ob = c.rit[c.rit["material_group"] == "OB"] if len(c.rit) else c.rit
ob_bcm = ob["volume"].sum() if len(ob) else 0
fleet = f[f["type"].isin(["Hauling", "Loading"])]["liters"].sum()
rec = c.receipt["liters"].sum() if len(c.receipt) else 0
r = st.columns(5)
r[0].metric("Consume", f"{fmt_num(f['liters'].sum())} L")
r[1].metric("Receipt", f"{fmt_num(rec)} L")
r[2].metric("Receipt − consume", f"{fmt_num(rec - f['liters'].sum())} L")
r[3].metric("Fuel ratio site", f"{fmt_num(f['liters'].sum() / ob_bcm, 2)} L/BCM" if ob_bcm else "—",
            help="Seluruh fuel / OB BCM")
r[4].metric("Fuel ratio hauling+loading", f"{fmt_num(fleet / ob_bcm, 2)} L/BCM" if ob_bcm else "—",
            help="Fuel unit Type Hauling & Loading / OB BCM")

a, b = st.columns(2)
with a:
    d = f.groupby("date")["liters"].sum().cumsum()
    rr = c.receipt.groupby("date")["liters"].sum().cumsum() if len(c.receipt) else pd.Series(dtype=float)
    fig = go.Figure()
    fig.add_scatter(x=d.index, y=d.values, name="Consume kumulatif", line=dict(color="#E5484D", width=3))
    if len(rr):
        fig.add_scatter(x=rr.index, y=rr.values, name="Receipt kumulatif", line=dict(color="#30A46C", width=3))
    fig.update_layout(title="Receipt vs consume kumulatif (L)")
    dash.plot(fig)
with b:
    if len(ob):
        per = pd.DataFrame({"L": f.groupby("site")["liters"].sum(), "BCM": ob.groupby("site")["volume"].sum()})
        per["ratio"] = per["L"] / per["BCM"]
        dash.ranking(per.reset_index(), "site", "ratio", "Fuel ratio per site (L/BCM)", "#F0A63C", pct=False)

a, b, cc = st.columns(3)
with a:
    dash.ranking(f.groupby("type", dropna=False)["liters"].sum().reset_index().fillna({"type": "UNMAPPED"}), "type",
                 "liters", "Liter per Type", dash.COL_TYPE, pct=False)
with b:
    dash.ranking(f.groupby("model", dropna=False)["liters"].sum().reset_index().fillna({"model": "—"}), "model",
                 "liters", "Liter per Model (15)", dash.COL_MODEL, pct=False)
with cc:
    dash.ranking(f.groupby("unit_id")["liters"].sum().reset_index(), "unit_id", "liters", "Liter per Unit (15)",
                 dash.COL_UNIT, pct=False)

st.subheader("Liter per jam HM per unit")
hm = c.ev.groupby("unit_id").agg(hm_awal=("hm_start", "min"), hm_akhir=("hm_end", "max"))
hm["jam_hm"] = (hm["hm_akhir"] - hm["hm_awal"]).clip(lower=0)
u = f.groupby(["unit_id", "type", "model"], dropna=False)["liters"].sum().reset_index().merge(
    hm["jam_hm"], left_on="unit_id", right_index=True, how="left")
u["l_per_jam_hm"] = u["liters"] / u["jam_hm"].replace(0, np.nan)
st.dataframe(u.sort_values("liters", ascending=False), hide_index=True, width="stretch", height=360,
             column_config={"jam_hm": st.column_config.NumberColumn(format="%.1f"),
                            "l_per_jam_hm": st.column_config.NumberColumn("L / jam HM", format="%.1f")})
excel_download(u, "fuel_per_unit.xlsx", key="dl_fu")

out = f[f["outlier"]].sort_values("liters", ascending=False)
st.subheader(f"Pengisian outlier ({len(out)})")
st.caption("Di atas persentil 99 per model; perlu dicek (salah input atau pengisian ke tangki lain).")
st.dataframe(out[["date", "shift", "unit_id", "model", "liters"]], hide_index=True, width="stretch", height=260)
