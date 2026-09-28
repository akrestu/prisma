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
    from core import hourly as H
    from core.config import now_wib
    p_date, p_shift, _ = H.production_hour(now_wib())
    with c:
        d1, d2 = st.columns(2)
        day = d1.date_input("Date", p_date, max_value=p_date, key="tv_h_date")
        sh = d2.segmented_control("Shift", list(H.SHIFTS), default=p_shift, key="tv_h_shift") or p_shift
    live = (day, sh) == (p_date, p_shift)
    st.caption("The shift running now, as the TV shows it (refreshed every minute on the TV)." if live else
               f"{day:%d %b %Y} {sh}: a past shift. The TV itself always shows the shift running now.")
    show_hourly(site, kiosk=False, date=None if live else day, shift=None if live else sh)
else:
    with c:
        period = st.segmented_control("Period", PERIODS, default="daily", format_func=PERIOD_LABEL.get,
                                      key="tv_period") or "daily"
    st.caption("Exactly what the site TV shows (PUBLISHED data only). Each TV's screen and period are set in "
               "Admin → TV devices.")
    show(site, kiosk=False, period=period)
