"""Preview TV: tampilan yang sama dengan layar TV site, dibuka dari aplikasi biasa."""
import streamlit as st

from core.config import UNMAPPED
from core.ui import require, sites_for
from pages.tv.screen import show

user = require("preview_tv")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title("Preview TV")
if not sites:
    st.info("Belum ada site.")
    st.stop()
site = st.segmented_control("Site", sites, default=sites[0], key="tv_site") or sites[0]
st.caption("Persis seperti yang tampil di TV site (hanya data PUBLISHED). Di TV, layar diperbarui otomatis tiap 5 menit.")
show(site, kiosk=False)
