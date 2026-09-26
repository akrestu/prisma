"""Data quality: temuan per aturan dan tingkat untuk data PUBLISHED yang dipilih."""
import plotly.express as px
import streamlit as st

from core import dash
from core.ui import excel_download

SEV = {"critical": "kritis", "warn": "perlu dicek", "info": "info (sudah ditangani)"}
c = dash.context("data_quality", unit_filter=False)
st.title("Data quality")
dq = c.dq()
if dq.empty:
    st.success("Tidak ada temuan data quality.")
    st.stop()

cnt = dq["severity"].value_counts()
r = st.columns(3)
for col, key in zip(r, SEV):
    col.metric(SEV[key].capitalize(), int(cnt.get(key, 0)))

g = dq.groupby(["rule", "severity"]).size().reset_index(name="temuan")
fig = px.bar(g.sort_values("temuan"), x="temuan", y="rule", color="severity", orientation="h",
             color_discrete_map={"critical": "#E5484D", "warn": "#F5B400", "info": "#7F95C4"})
fig.update_layout(title="Temuan per aturan", yaxis_title="")
dash.plot(fig, max(300, 28 * len(g) + 80))

a, b = st.columns(2)
sev = a.multiselect("Tingkat", list(SEV), format_func=SEV.get, key="dq_sev")
rule = b.multiselect("Aturan", sorted(dq["rule"].unique()), key="dq_rule")
v = dq
if sev:
    v = v[v["severity"].isin(sev)]
if rule:
    v = v[v["rule"].isin(rule)]
st.dataframe(v[["site", "severity", "rule", "sheet", "row_ref", "unit_id", "date", "detail"]], hide_index=True,
             width="stretch", height=420,
             column_config={"row_ref": st.column_config.NumberColumn("baris Excel", format="%d")})
excel_download(v, "data_quality.xlsx")
st.caption("Kolom 'baris Excel' menunjuk nomor baris di file sumber supaya mudah diperbaiki.")
