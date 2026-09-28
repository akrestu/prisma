"""TV Preview: the same screens a site TV shows, opened from the regular app."""
import streamlit as st

from core.config import UNMAPPED
from core.periods import PERIOD_LABEL, PERIODS
from core.ui import require, sites_for
from pages.tv.screen import SCREENS, show, show_hourly

user = require("preview_tv")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title("TV preview")
if not sites:
    st.info("No sites yet.")
    st.stop()
a, b, c = st.columns([2, 2, 3])
with a:
    site = st.segmented_control("Site", sites, default=sites[0], key="tv_site") or sites[0]
with b:
    screen = st.segmented_control("Screen", list(SCREENS), default="equipment", format_func=SCREENS.get,
                                  key="tv_screen") or "equipment"
if screen == "hourly":
    st.caption("Hourly production as the TV shows it now (flash data, refreshed every minute on the TV).")
    show_hourly(site, kiosk=False)
else:
    with c:
        period = st.segmented_control("Period", PERIODS, default="daily", format_func=PERIOD_LABEL.get,
                                      key="tv_period") or "daily"
    st.caption("Exactly what the site TV shows (PUBLISHED data only). Each TV's screen and period are set in "
               "Admin → TV devices.")
    show(site, kiosk=False, period=period)
