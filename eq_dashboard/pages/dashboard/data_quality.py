"""Data quality: findings by rule and severity for the selected PUBLISHED data."""
import plotly.express as px
import streamlit as st

from core import dash
from core import theme as T
from core.ui import excel_download

SEV = {"critical": "critical", "warn": "to check", "info": "info (handled automatically)"}
c = dash.context("data_quality", unit_filter=False)
st.title("Data quality")
dq = c.dq()
if dq.empty:
    st.success("No data quality findings.")
    st.stop()

cnt = dq["severity"].value_counts()
dash.summary(f"{int(cnt.get('critical', 0))} critical findings block auto-approval",
             f"{int(cnt.get('warn', 0))} findings to check and {int(cnt.get('info', 0))} handled automatically")
r = st.columns(3)
for col, key in zip(r, SEV, strict=True):
    col.metric(SEV[key].capitalize(), int(cnt.get(key, 0)))

g = dq.groupby(["rule", "severity"]).size().reset_index(name="findings")
fig = px.bar(g.sort_values("findings"), x="findings", y="rule", color="severity", orientation="h",
             color_discrete_map={"critical": T.MISS, "warn": T.ACCENT, "info": T.READY},
             category_orders={"severity": ["critical", "warn", "info"]}, labels={"severity": ""})
fig.update_layout(title="Findings by rule", yaxis_title="", yaxis_categoryorder="total ascending")
dash.plot(fig, max(300, 28 * len(g) + 80))

a, b = st.columns(2)
sev = a.multiselect("Severity", list(SEV), format_func=SEV.get, key="dq_sev")
rule = b.multiselect("Rule", sorted(dq["rule"].unique()), key="dq_rule")
v = dq
if sev:
    v = v[v["severity"].isin(sev)]
if rule:
    v = v[v["rule"].isin(rule)]
st.dataframe(v[["site", "severity", "rule", "sheet", "row_ref", "unit_id", "date", "detail"]], hide_index=True,
             width="stretch", height=420,
             column_config={"row_ref": st.column_config.NumberColumn("Excel row", format="%d")})
excel_download(v, "data_quality.xlsx")
st.caption("'Excel row' is the row number in the source file, to make corrections easy.")
