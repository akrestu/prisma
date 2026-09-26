"""Time distribution: R/I/S/D share, idle & standby reasons, client vs internal standby, DS vs NS."""
import plotly.graph_objects as go
import streamlit as st

from core import dash, metrics
from core import theme as T
from core.ui import excel_download, fmt_num

c = dash.context("time_distribution")
st.title("Time distribution")

b = metrics.time_buckets(c.ev).iloc[0]
client_codes = dash.client_standby_codes()
s_all = c.ev[c.ev["category"] == "S"]
client_share = s_all.loc[s_all["reason_code"].isin(client_codes), "hours"].sum() / s_all["hours"].sum() if len(s_all) else 0
dash.summary(f"Standby is {b['S'] / b['T']:.0%} of all hours and down is {b['D'] / b['T']:.0%}",
             f"{client_share:.0%} of standby is caused by the client")
r = st.columns(5)
r[0].metric("Total hours", fmt_num(b["T"]))
for i, cat in enumerate("RISD", start=1):
    r[i].metric(dash.CAT_LABEL[cat], f"{b[cat] / b['T']:.1%}", f"{fmt_num(b[cat])} h", delta_color="off")

a, bb = st.columns(2)
with a:
    dash.stacked_dist(c.ev, "type", "Hours by type")
with bb:
    dash.stacked_dist(c.ev, "model", "Hours by model (top 20)")

client = dash.client_standby_codes()
sb = c.ev[c.ev["category"] == "S"].assign(grp=lambda d: d["reason_code"].isin(client).map(
    {True: "Client", False: "Internal"}))
a, bb, cc = st.columns([1.2, 1.2, 0.8])
with a:
    dash.pareto(c.ev[c.ev["category"] == "I"], "reason_text", "hours", "Idle hours Pareto", T.ACCENT)
with bb:
    dash.pareto(sb, "reason_text", "hours", "Standby hours Pareto", T.STANDBY)
with cc:
    g = sb.groupby("grp")["hours"].sum()
    fig = go.Figure(go.Pie(labels=g.index, values=g.values, hole=.55, marker_colors=[T.IDLE, T.STANDBY]))
    fig.update_layout(title="Standby: client vs internal")
    dash.plot(fig, 380)
    st.caption("Client reason codes are set by the Admin on the PM intervals & standby page.")

st.subheader("Day shift vs night shift")
ds = metrics.availability(metrics.time_buckets(c.ev, ["shift"]))
fig = go.Figure()
for cat in "RISD":
    fig.add_bar(x=ds.index, y=ds[cat] / ds["T"], name=dash.CAT_LABEL[cat], marker_color=dash.COL_CAT[cat])
fig.update_layout(barmode="stack", yaxis=dict(tickformat=".0%"), title="Hour share by shift")
dash.plot(fig, 320)

st.subheader("Hours by reason code")
tab = (c.ev.groupby(["category", "reason_code", "reason_text"], dropna=False)["hours"].sum().reset_index()
       .assign(category=lambda d: d["category"].map(dash.CAT_LABEL)).sort_values("hours", ascending=False))
tab.columns = ["Category", "Code", "Reason", "Hours"]
st.dataframe(tab, hide_index=True, width="stretch", column_config={"Hours": st.column_config.NumberColumn(format="%.1f")})
excel_download(tab, "hours_by_reason.xlsx")
