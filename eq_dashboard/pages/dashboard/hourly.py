"""Hourly production (flash data): the TV screen for any site and shift, a daily trend of the month and the raw lines."""

import plotly.graph_objects as go
import streamlit as st

from core import dash
from core import hourly as H
from core import theme as T
from core.config import UNMAPPED, now_wib
from core.ui import excel_download, require, sites_for
from db import repo
from db.engine import session_scope
from pages.tv.screen import show_hourly

user = require("hourly")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title("Hourly production")
if not sites:
    st.info("No site access.")
    st.stop()

p_date, p_shift, _ = H.production_hour(now_wib())
a, b, c = st.columns([1.3, 1, 1])
site = a.selectbox("Site", sites, key="hp_site")
date = b.date_input("Production date", p_date, key="hp_date", max_value=p_date)
shift = c.segmented_control("Shift", list(H.SHIFTS), default=p_shift, key="hp_shift") or p_shift
live = (date, shift) == (p_date, p_shift)
st.caption(("Live: the shift running now. " if live else "")
           + "Flash data entered per hour, not approved; the official month figures come from Data_Prod.")

show_hourly(site, kiosk=False, date=None if live else date, shift=None if live else shift)

with session_scope() as s:
    month = date.replace(day=1)
    rows = repo.hourly_range(s, [site], month, date)
if rows.empty:
    st.info("No hourly input for this site this month yet.")
    st.stop()

long = H.to_long(rows)
daily = long.pivot_table(index="date", columns="material_group", values="volume", aggfunc="sum", fill_value=0)
st.subheader(f"Flash production per day · {month:%B %Y}")
fig = go.Figure()
if "OB" in daily:
    fig.add_bar(x=daily.index, y=daily["OB"], name="OB (BCM)", marker_color=T.ACCENT)
if "CG" in daily:
    fig.add_scatter(x=daily.index, y=daily["CG"], name="Coal (t)", yaxis="y2", line=dict(color=T.READY, width=3))
plan = dash.plan_range([site], month, date)
if plan["ob_plan"].notna().any():
    fig.add_scatter(x=plan["date"], y=plan["ob_plan"], name="OB plan", line=dict(color=T.IDLE, dash="dash"))
fig.update_layout(yaxis=dict(title="BCM", tickformat=","), yaxis2=dict(title="t", overlaying="y", side="right",
                                                                           tickformat=",", showgrid=False))
dash.plot(fig, 340)

shift_rows = rows[(rows["date"] == date) & (rows["shift"] == shift)]
st.subheader(f"Lines · {date:%d %b} {shift}")
if shift_rows.empty:
    st.caption("No input for this shift.")
else:
    show = shift_rows.rename(columns=dict(zip(H.R, H.SLOTS[shift], strict=True)))
    cols = ["line", "loader", "loader_model", "operator", "material", "hauler_model", "muatan", "pit", "disposal",
            "distance_m", "target_per_hour", *H.SLOTS[shift], "remark_code", "remark"]
    st.dataframe(show[cols], hide_index=True, width="stretch")
    excel_download(show[cols], f"hourly_{site}_{date:%Y-%m-%d}_{shift}.xlsx", key="hp_dl")
excel_download(long.drop(columns=["updated_at"], errors="ignore"), f"hourly_{site}_{month:%Y-%m}.xlsx",
               label="Download month (one row per line × hour)", key="hp_dl_m")
