"""TV devices: create Display links, set the period per TV, revoke or regenerate tokens, see which TVs are online."""
import datetime as dt

import streamlit as st
from sqlalchemy import select

from auth import display
from core.config import UNMAPPED, WIB
from core.ingest import audit
from core.periods import PERIOD_LABEL, PERIODS
from core.ui import require, sites_for
from db import models as m
from db.engine import session_scope

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
    c1, c2, c3 = st.columns([2, 1, 1])
    name = c1.text_input("TV name", placeholder="MAS control room TV")
    site = c2.selectbox("Site", [x for x in sites_for(user) if x != UNMAPPED])
    period = c3.selectbox("Period", PERIODS, index=1, format_func=PERIOD_LABEL.get)
    if st.form_submit_button("Create TV link", type="primary"):
        if not name.strip():
            st.error("Enter a TV name.")
        else:
            with session_scope() as s:
                dev, token = display.create_device(s, name.strip(), site, user.id)
                dev.period = period
                audit(s, user.username, "display_create", site, f"{name.strip()} ({period})")
            st.session_state["new_display_link"] = (name.strip(), link(token))
            st.rerun()

with session_scope() as s:
    rows = [(d.id, d.name, d.site_code, d.period, d.active, d.last_seen)
            for d in s.scalars(select(m.DisplayDevice).order_by(m.DisplayDevice.site_code, m.DisplayDevice.name))]
if not rows:
    st.info("No TV devices yet.")
    st.stop()

now = dt.datetime.now(dt.UTC)
st.subheader("TVs")
for did, name, site, period, active, seen in rows:
    online = active and seen is not None and now - seen < dt.timedelta(minutes=10)
    state = ":yellow-badge[online]" if online else (":gray-badge[offline]" if active else ":orange-badge[revoked]")
    seen_txt = seen.astimezone(WIB).strftime("%d %b %H:%M") if seen else "never"
    with st.container(border=True):
        a, p, b, c, d = st.columns([3.2, 1.6, 1.6, 1, 1])
        a.markdown(f"**{name}** · {site} {state}  \nlast seen: {seen_txt} WIB")
        new_period = p.selectbox("Period", PERIODS, index=PERIODS.index(period) if period in PERIODS else 1,
                                 format_func=PERIOD_LABEL.get, key=f"per{did}", label_visibility="collapsed")
        if new_period != period:
            with session_scope() as s:
                s.get(m.DisplayDevice, did).period = new_period
                audit(s, user.username, "display_period", site, f"{name}: {period} → {new_period}")
            st.toast(f"{name}: {PERIOD_LABEL[new_period]} (applied on the TV's next refresh, ≤ 5 min)")
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
