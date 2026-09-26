"""Kelola perangkat TV: buat link Display, cabut, buat ulang token, pantau TV online."""
import datetime as dt

import pandas as pd
import streamlit as st
from sqlalchemy import select

from auth import display
from core.config import UNMAPPED
from core.ingest import audit
from core.ui import require, sites_for
from db import models as m
from db.engine import session_scope

user = require("display_devices")
st.title("Perangkat TV")
st.caption("Setiap TV memakai link rahasia yang terkunci ke satu site dan hanya menampilkan layar TV (read-only). "
           "Link hanya ditampilkan sekali saat dibuat; simpan di TV/mini-PC.")

base = st.text_input("Alamat aplikasi", value=st.session_state.get("tv_base", "http://localhost:8501"),
                     help="Di production isi domain HTTPS, mis. https://dashboard.perusahaan.co.id")
st.session_state["tv_base"] = base.rstrip("/")


def link(token: str) -> str:
    return f"{st.session_state['tv_base']}/?display={token}"


new = st.session_state.pop("new_display_link", None)
if new:
    st.success(f"Link untuk **{new[0]}** (salin sekarang, tidak akan ditampilkan lagi):")
    st.code(new[1], language=None)
    st.caption(f'Setup TV: jalankan Chrome/Edge dengan `--kiosk "{new[1]}"`, aktifkan auto-start, matikan sleep & screensaver.')

with st.form("new_device", clear_on_submit=True):
    c1, c2 = st.columns(2)
    name = c1.text_input("Nama TV", placeholder="TV ruang kontrol MAS")
    site = c2.selectbox("Site", [x for x in sites_for(user) if x != UNMAPPED])
    if st.form_submit_button("Buat link TV", type="primary"):
        if not name.strip():
            st.error("Isi nama TV.")
        else:
            with session_scope() as s:
                dev, token = display.create_device(s, name.strip(), site, user.id)
                audit(s, user.username, "display_create", site, name.strip())
            st.session_state["new_display_link"] = (name.strip(), link(token))
            st.rerun()

with session_scope() as s:
    devs = list(s.scalars(select(m.DisplayDevice).order_by(m.DisplayDevice.site_code, m.DisplayDevice.name)))
    rows = [(d.id, d.name, d.site_code, d.active, d.last_seen, d.created_at) for d in devs]
if not rows:
    st.info("Belum ada perangkat TV.")
    st.stop()

now = dt.datetime.now(dt.timezone.utc)
st.subheader("Daftar TV")
for did, name, site, active, seen, created in rows:
    online = active and seen is not None and now - seen < dt.timedelta(minutes=10)
    state = ":green-badge[online]" if online else (":gray-badge[offline]" if active else ":red-badge[dicabut]")
    seen_txt = seen.astimezone(dt.timezone(dt.timedelta(hours=7))).strftime("%d %b %H:%M") if seen else "belum pernah"
    with st.container(border=True):
        a, b, c, d = st.columns([4, 2, 1.2, 1.2])
        a.markdown(f"**{name}** · {site} {state}  \nterakhir terlihat: {seen_txt} WIB")
        if b.button("Buat ulang link", key=f"regen{did}"):
            with session_scope() as s:
                token = display.regenerate(s, s.get(m.DisplayDevice, did))
                audit(s, user.username, "display_regenerate", site, name)
            st.session_state["new_display_link"] = (name, link(token))
            st.rerun()
        if active and c.button("Cabut", key=f"rev{did}"):
            with session_scope() as s:
                s.get(m.DisplayDevice, did).active = False
                audit(s, user.username, "display_revoke", site, name)
            st.rerun()
        if d.button("Hapus", key=f"del{did}"):
            with session_scope() as s:
                s.delete(s.get(m.DisplayDevice, did))
                audit(s, user.username, "display_delete", site, name)
            st.rerun()
