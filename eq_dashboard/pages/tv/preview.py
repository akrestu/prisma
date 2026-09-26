"""TV Preview: the same screen a site TV shows, opened from the regular app."""
import streamlit as st

from core.config import UNMAPPED
from core.periods import PERIOD_LABEL, PERIODS
from core.ui import require, sites_for
from pages.tv.screen import show

user = require("preview_tv")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title("TV preview")
if not sites:
    st.info("No sites yet.")
    st.stop()
a, b = st.columns([2, 3])
with a:
    site = st.segmented_control("Site", sites, default=sites[0], key="tv_site") or sites[0]
with b:
    period = st.segmented_control("Period", PERIODS, default="daily", format_func=PERIOD_LABEL.get,
                                  key="tv_period") or "daily"
st.caption("Exactly what the site TV shows (PUBLISHED data only). Each TV's period is set in Admin → TV devices; "
           "TVs refresh automatically every 5 minutes.")
show(site, kiosk=False, period=period)
