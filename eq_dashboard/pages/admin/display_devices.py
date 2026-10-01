"""TV devices: create Display links, set the period per TV, revoke or regenerate tokens, see which TVs are online."""
import datetime as dt

import streamlit as st
from sqlalchemy import select

from auth import display
from core.config import UNMAPPED, WIB, today_wib
from core.ingest import audit
from core.periods import PERIOD_LABEL, PERIODS
from core.ui import require, sites_for
from db import models as m
from db.engine import session_scope
from pages.tv.screen import SCREENS

user = require("display_devices")
st.title("TV devices")
st.caption("Each TV uses a secret link locked to one site that only shows the TV screen (read-only). "
           "The link is shown once when created, so store it on the TV / mini-PC.")

base = st.text_input("App address", value=st.session_state.get("tv_base", "http://localhost:8501"),
                     help="In production use the HTTPS domain, e.g. https://dashboard.company.com")
st.session_state["tv_base"] = base.rstrip("/")


def link(token: str) -> str:
    return f"{st.session_state['tv_base']}/?display={token}"


new = st.session_state.pop("new_display_link", None)
if new:
    st.success(f"Link for **{new[0]}** (copy it now, it will not be shown again):")
    st.code(new[1], language=None)
    st.caption(f'TV setup: start Chrome/Edge with `--kiosk "{new[1]}"`, enable auto-start, disable sleep & screensaver.')

with st.form("new_device", clear_on_submit=True):
    c1, c2, c3, c4 = st.columns([2, 1, 1.2, 1])
    name = c1.text_input("TV name", placeholder="MAS control room TV")
    site = c2.selectbox("Site", [x for x in sites_for(user) if x != UNMAPPED])
    screen = c3.selectbox("Screen", list(SCREENS), format_func=SCREENS.get,
                          help="Equipment & monthly: availability, reliability, production. Hourly Production: "
                               "trips per fleet per hour (flash data), refreshed every minute.")
    period = c4.selectbox("Period", PERIODS, index=1, format_func=PERIOD_LABEL.get,
                          help="Used by the Equipment & monthly screen")
    if st.form_submit_button("Create TV link", type="primary"):
        if not name.strip():
            st.error("Enter a TV name.")
        else:
            with session_scope() as s:
                dev, token = display.create_device(s, name.strip(), site, user.id)
                dev.period, dev.screen = period, screen
                audit(s, user.username, "display_create", site, f"{name.strip()} ({screen}, {period})")
            st.session_state["new_display_link"] = (name.strip(), link(token))
            st.rerun()

with session_scope() as s:
    rows = [(d.id, d.name, d.site_code, d.period, d.active, d.last_seen, d.screen, d.hourly_date, d.hourly_shift,
             d.review_from, d.review_to)
            for d in s.scalars(select(m.DisplayDevice).order_by(m.DisplayDevice.site_code, m.DisplayDevice.name))]
if not rows:
    st.info("No TV devices yet.")
    st.stop()

now = dt.datetime.now(dt.UTC)
st.subheader("TVs")
for did, name, site, period, active, seen, screen, h_date, h_shift, r_from, r_to in rows:
    online = active and seen is not None and now - seen < dt.timedelta(minutes=10)
    state = ":yellow-badge[online]" if online else (":gray-badge[offline]" if active else ":orange-badge[revoked]")
    seen_txt = seen.astimezone(WIB).strftime("%d %b %H:%M") if seen else "never"
    with st.container(border=True):
        a, q, p, b, c, d = st.columns([2.8, 1.6, 1.4, 1.5, 0.9, 0.9])
        review_txt = (f" :orange-badge[review {r_from:%d %b} – {r_to:%d %b %Y}]"
                      if screen != "hourly" and r_from and r_to else "")
        a.markdown(f"**{name}** · {site} {state}{review_txt}  \nlast seen: {seen_txt} WIB")
        new_screen = q.selectbox("Screen", list(SCREENS), index=list(SCREENS).index(screen) if screen in SCREENS
                                 else 0, format_func=SCREENS.get, key=f"scr{did}", label_visibility="collapsed")
        if new_screen != screen:
            with session_scope() as s:
                s.get(m.DisplayDevice, did).screen = new_screen
                audit(s, user.username, "display_screen", site, f"{name}: {screen} → {new_screen}")
            st.toast(f"{name}: {SCREENS[new_screen]} (applied on the TV within a minute)")
            st.rerun()
        if screen == "hourly":
            live_now = h_date is None
            p.markdown("**Report**  \n" + ("Live · shift running now" if live_now
                                             else f"Fixed · {h_date:%d %b %Y} {h_shift}"))
            # which report the hourly screen shows: the shift running now, or a fixed date and shift
            r1, r2, r3, _ = st.columns([1.6, 1.3, 1, 2.6])
            mode = r1.segmented_control("Report on this TV", ["Live", "Fixed date"],
                                        default="Live" if live_now else "Fixed date", key=f"hmode{did}",
                                        help="Live follows the shift running now; Fixed date keeps one report on "
                                             "screen until you change it") or "Live"
            fixed = mode == "Fixed date"
            pick_d = r2.date_input("Report date", h_date or today_wib(), max_value=today_wib(), key=f"hdate{did}",
                                   disabled=not fixed)
            pick_s = r3.segmented_control("Shift", ["DS", "NS"], default=h_shift or "DS", key=f"hshift{did}",
                                          disabled=not fixed) or "DS"
            if not fixed:
                pick_d, pick_s = None, None
            if (pick_d, pick_s) != (h_date, h_shift):
                with session_scope() as s:
                    dev = s.get(m.DisplayDevice, did)
                    dev.hourly_date, dev.hourly_shift = pick_d, pick_s
                    audit(s, user.username, "display_hourly_report", site,
                          f"{name}: {'live' if pick_d is None else f'{pick_d:%Y-%m-%d} {pick_s}'}")
                st.toast(f"{name}: " + ("live shift" if pick_d is None else f"report {pick_d:%d %b %Y} {pick_s}")
                         + " (applied on the TV within a minute)")
                st.rerun()
            new_period = period
        else:
            new_period = p.selectbox("Period", PERIODS, index=PERIODS.index(period) if period in PERIODS else 1,
                                     format_func=PERIOD_LABEL.get, key=f"per{did}", label_visibility="collapsed")
            # which data the equipment screen shows: live (latest month / year) or a fixed range to review
            live_now = r_from is None
            r1, r2, _ = st.columns([1.6, 2.3, 3.6])
            mode = r1.segmented_control("Data on this TV", ["Live", "Review range"],
                                        default="Live" if live_now else "Review range", key=f"rmode{did}",
                                        help="Live follows the newest published data. Review range keeps a fixed "
                                             "period on screen (marked REVIEW) until you switch back to Live.") or "Live"
            t = today_wib()
            rng = r2.date_input("From – to", (r_from or t.replace(day=1), r_to or t), max_value=t, key=f"rrng{did}",
                                format="DD/MM/YYYY", disabled=mode == "Live")
            pick = (None, None)
            if mode == "Review range":
                pick = tuple(rng) if isinstance(rng, (list, tuple)) and len(rng) == 2 else (r_from, r_to)
            if pick != (r_from, r_to) and (pick == (None, None) or all(pick)):
                with session_scope() as s:
                    dev = s.get(m.DisplayDevice, did)
                    dev.review_from, dev.review_to = pick
                    audit(s, user.username, "display_review_range", site,
                          f"{name}: {'live' if pick[0] is None else f'{pick[0]:%Y-%m-%d} – {pick[1]:%Y-%m-%d}'}")
                st.toast(f"{name}: " + ("live data" if pick[0] is None else f"review {pick[0]:%d %b %Y} – {pick[1]:%d %b %Y}")
                         + " (applied on the TV within a minute)")
                st.rerun()
        if new_period != period:
            with session_scope() as s:
                s.get(m.DisplayDevice, did).period = new_period
                audit(s, user.username, "display_period", site, f"{name}: {period} → {new_period}")
            st.toast(f"{name}: {PERIOD_LABEL[new_period]} (applied on the TV within a minute)")
            st.rerun()
        if b.button("Regenerate link", key=f"regen{did}"):
            with session_scope() as s:
                token = display.regenerate(s, s.get(m.DisplayDevice, did))
                audit(s, user.username, "display_regenerate", site, name)
            st.session_state["new_display_link"] = (name, link(token))
            st.rerun()
        if active and c.button("Revoke", key=f"rev{did}"):
            with session_scope() as s:
                s.get(m.DisplayDevice, did).active = False
                audit(s, user.username, "display_revoke", site, name)
            st.rerun()
        if d.button("Delete", key=f"del{did}"):
            with session_scope() as s:
                s.delete(s.get(m.DisplayDevice, did))
                audit(s, user.username, "display_delete", site, name)
            st.rerun()
