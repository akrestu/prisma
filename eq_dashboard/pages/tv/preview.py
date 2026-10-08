"""TV Preview: the same screens a site TV shows, opened from the regular app."""
import streamlit as st

from core.config import UNMAPPED
from core.periods import PERIOD_LABEL, PERIODS
from core.ui import require, sites_for
from pages.tv.screen import SCREENS, show, show_hourly, theme_picker

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
               f"{day:%d %b %Y} {sh}: a past shift. To keep it on a TV, set it in TV → TV devices.")
    theme = theme_picker(st, "tv_h_theme")
    show_hourly(site, kiosk=False, date=None if live else day, shift=None if live else sh, theme=theme)
else:
    from core.config import today_wib
    with c:
        period = st.segmented_control("Period", PERIODS, default="daily", format_func=PERIOD_LABEL.get,
                                      key="tv_period") or "daily"
    m1, m2, _ = st.columns([1.4, 2.2, 3.4])
    mode = m1.segmented_control("Data", ["Live", "Review range"], default="Live", key="tv_mode") or "Live"
    review = None
    if mode == "Review range":
        t = today_wib()
        rng = m2.date_input("From – to", (t.replace(day=1), t), max_value=t, key="tv_review", format="DD/MM/YYYY")
        review = tuple(rng) if isinstance(rng, (list, tuple)) and len(rng) == 2 else None
    st.caption("Exactly what the site TV shows (PUBLISHED data only). Each TV's screen, period and live/review "
               "range are set in TV → TV devices.")
    show(site, kiosk=False, period=period, review=review)
