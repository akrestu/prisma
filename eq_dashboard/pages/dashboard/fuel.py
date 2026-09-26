"""Fuel: consumption vs receipts, fuel ratio per site & fleet, litres by type/model/unit, L per HM hour, outliers."""
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
    st.info("No fuel data for this selection.")
    st.stop()

ob = c.rit[c.rit["material_group"] == "OB"] if len(c.rit) else c.rit
ob_bcm = ob["volume"].sum() if len(ob) else 0
fleet = f[f["type"].isin(["Hauling", "Loading"])]["liters"].sum()
rec = c.receipt["liters"].sum() if len(c.receipt) else 0
r = st.columns(5)
r[0].metric("Consumption", f"{fmt_num(f['liters'].sum())} L")
r[1].metric("Receipts", f"{fmt_num(rec)} L")
r[2].metric("Receipts − consumption", f"{fmt_num(rec - f['liters'].sum())} L")
r[3].metric("Site fuel ratio", f"{fmt_num(f['liters'].sum() / ob_bcm, 2)} L/BCM" if ob_bcm else "—",
            help="All fuel / OB BCM")
r[4].metric("Hauling + loading ratio", f"{fmt_num(fleet / ob_bcm, 2)} L/BCM" if ob_bcm else "—",
            help="Fuel of Hauling & Loading units / OB BCM")

a, b = st.columns(2)
with a:
    d = f.groupby("date")["liters"].sum().cumsum()
    rr = c.receipt.groupby("date")["liters"].sum().cumsum() if len(c.receipt) else pd.Series(dtype=float)
    fig = go.Figure()
    fig.add_scatter(x=d.index, y=d.values, name="Cumulative consumption", line=dict(color="#E5484D", width=3))
    if len(rr):
        fig.add_scatter(x=rr.index, y=rr.values, name="Cumulative receipts", line=dict(color="#30A46C", width=3))
    fig.update_layout(title="Receipts vs consumption, cumulative (L)")
    dash.plot(fig)
with b:
    if len(ob):
        per = pd.DataFrame({"L": f.groupby("site")["liters"].sum(), "BCM": ob.groupby("site")["volume"].sum()})
        per["ratio"] = per["L"] / per["BCM"]
        dash.ranking(per.reset_index(), "site", "ratio", "Fuel ratio by site (L/BCM)", "#F0A63C", pct=False, digits=2)

a, b, cc = st.columns(3)
with a:
    dash.ranking(f.groupby("type", dropna=False)["liters"].sum().reset_index().fillna({"type": "UNMAPPED"}), "type",
                 "liters", "Litres by type", dash.COL_TYPE, pct=False)
with b:
    dash.ranking(f.groupby("model", dropna=False)["liters"].sum().reset_index().fillna({"model": "—"}), "model",
                 "liters", "Litres by model (top 15)", dash.COL_MODEL, pct=False)
with cc:
    dash.ranking(f.groupby("unit_id")["liters"].sum().reset_index(), "unit_id", "liters", "Litres by unit (top 15)",
                 dash.COL_UNIT, pct=False)

st.subheader("Litres per HM hour by unit")
hm = c.ev.groupby("unit_id").agg(hm_start=("hm_start", "min"), hm_end=("hm_end", "max"))
hm["hm_hours"] = (hm["hm_end"] - hm["hm_start"]).clip(lower=0)
u = f.groupby(["unit_id", "type", "model"], dropna=False)["liters"].sum().reset_index().merge(
    hm["hm_hours"], left_on="unit_id", right_index=True, how="left")
u["l_per_hm_hour"] = u["liters"] / u["hm_hours"].replace(0, np.nan)
st.dataframe(u.sort_values("liters", ascending=False), hide_index=True, width="stretch", height=360,
             column_config={"liters": st.column_config.NumberColumn(format="%,.0f"),
                            "hm_hours": st.column_config.NumberColumn("HM hours", format="%.1f"),
                            "l_per_hm_hour": st.column_config.NumberColumn("L / HM hour", format="%.1f")})
excel_download(u, "fuel_by_unit.xlsx", key="dl_fu")

out = f[f["outlier"]].sort_values("liters", ascending=False)
st.subheader(f"Outlier refuels ({len(out)})")
st.caption("Above the 99th percentile of the model; worth checking (entry error or filling another tank).")
st.dataframe(out[["date", "shift", "unit_id", "model", "liters"]], hide_index=True, width="stretch", height=260)
