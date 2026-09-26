"""Produktivitas loader & hauler: BCM per jam Ready (pembanding Ready+Idle), rit/jam, jarak angkut."""
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from core import dash
from core.ui import excel_download, fmt_num

c = dash.context("loader_fleet", unit_filter=False)
st.title("Loader & fleet")
ob = c.rit[c.rit["material_group"] == "OB"] if len(c.rit) else c.rit
if ob.empty:
    st.info("Tidak ada data ritase OB untuk pilihan ini.")
    st.stop()

hrs = c.ev.pivot_table(index="unit_id", columns="category", values="hours", aggfunc="sum", fill_value=0)
ready = hrs.get("R", pd.Series(dtype=float))
work = ready.add(hrs.get("I", pd.Series(dtype=float)), fill_value=0)


def wavg(g, col):
    return np.average(g[col], weights=g["rit"]) if g["rit"].sum() and g[col].notna().all() else np.nan


ld = ob.groupby("loader").agg(model=("loader_model", "first"), bcm=("volume", "sum"), rit=("rit", "sum"),
                             hauler=("hauler", "nunique"))
ld["jam_ready"] = ready.reindex(ld.index)
ld["jam_ready_idle"] = work.reindex(ld.index)
ld["bcm_per_jam"] = ld["bcm"] / ld["jam_ready"].replace(0, np.nan)
ld["bcm_per_jam_ri"] = ld["bcm"] / ld["jam_ready_idle"].replace(0, np.nan)
ld["jarak_h"] = ob.groupby("loader").apply(lambda g: wavg(g, "dist_h"), include_groups=False)
ld = ld.sort_values("bcm", ascending=False)

tot_ready = ld["jam_ready"].sum()
r = st.columns(4)
r[0].metric("Loader aktif", len(ld))
r[1].metric("BCM / jam Ready (fleet)", fmt_num(ld["bcm"].sum() / tot_ready, 1) if tot_ready else "—")
r[2].metric("Hauler aktif", fmt_num(ob["hauler"].nunique()))
r[3].metric("Jarak angkut rata-rata", f"{fmt_num(np.average(ob['dist_h'].fillna(0), weights=ob['rit']))} m",
            "berbobot ritase", delta_color="off")

a, b = st.columns(2)
with a:
    dash.ranking(ld.reset_index().dropna(subset=["bcm_per_jam"]), "loader", "bcm_per_jam",
                 "BCM per jam Ready per loader", dash.COL_MODEL, pct=False)
with b:
    fig = px.scatter(ld.reset_index().dropna(subset=["bcm_per_jam"]), x="jarak_h", y="bcm_per_jam", size="bcm",
                     color="model", hover_name="loader",
                     labels={"jarak_h": "Jarak horizontal rata-rata (m)", "bcm_per_jam": "BCM / jam Ready"})
    fig.update_layout(title="Jarak angkut vs produktivitas loader")
    dash.plot(fig, max(360, 26 * len(ld) + 80))

st.subheader("Loader")
show = ld.reset_index().rename(columns={"loader": "Loader", "model": "Model", "bcm": "BCM", "rit": "Rit",
                                        "hauler": "Hauler dilayani", "jam_ready": "Jam Ready",
                                        "jam_ready_idle": "Jam Ready+Idle", "bcm_per_jam": "BCM/jam Ready",
                                        "bcm_per_jam_ri": "BCM/jam Ready+Idle", "jarak_h": "Jarak H (m)"})
st.dataframe(show, hide_index=True, width="stretch",
             column_config={x: st.column_config.NumberColumn(format="%.1f") for x in
                            ["BCM", "Jam Ready", "Jam Ready+Idle", "BCM/jam Ready", "BCM/jam Ready+Idle", "Jarak H (m)"]})
excel_download(show, "produktivitas_loader.xlsx", key="dl_ld")

st.subheader("Hauler")
hl = ob.groupby(["hauler", "hauler_model"]).agg(rit=("rit", "sum"), bcm=("volume", "sum")).reset_index()
hl["jam_ready"] = hl["hauler"].map(ready)
hl["rit_per_jam"] = hl["rit"] / hl["jam_ready"].replace(0, np.nan)
hl["bcm_per_jam"] = hl["bcm"] / hl["jam_ready"].replace(0, np.nan)
a, b = st.columns([1, 1.4])
with a:
    mdl = hl.groupby("hauler_model").agg(rit=("rit", "sum"), jam=("jam_ready", "sum")).reset_index()
    mdl["rit_per_jam"] = mdl["rit"] / mdl["jam"].replace(0, np.nan)
    dash.ranking(mdl.dropna(subset=["rit_per_jam"]), "hauler_model", "rit_per_jam", "Rit per jam Ready per model",
                 dash.COL_UNIT, pct=False)
with b:
    st.dataframe(hl.sort_values("bcm", ascending=False), hide_index=True, width="stretch", height=420,
                 column_config={x: st.column_config.NumberColumn(format="%.2f") for x in
                                ["jam_ready", "rit_per_jam", "bcm_per_jam"]})

st.subheader("Jumlah hauler per loader per jam (rata-rata)")
per_h = ob.groupby(["loader", "date", "hour_slot"])["hauler"].nunique().groupby("loader").mean().sort_values()
fig = px.bar(per_h, orientation="h", labels={"value": "hauler / jam", "loader": ""})
fig.update_traces(marker_color=dash.COL_MODEL)
fig.update_layout(showlegend=False, title="Rata-rata hauler yang dilayani per jam aktif")
dash.plot(fig, max(300, 24 * len(per_h) + 80))
