"""Site (nama, aktif, auto-approve), alias ID loader/DT/unit, dan mapping tangki fuel → site."""
import pandas as pd
import streamlit as st
from sqlalchemy import delete, select

from core.ingest import audit
from core.ui import require
from db import models as m
from db import repo
from db.engine import session_scope

user = require("sites_mapping")
st.title("Site & mapping")
st.caption("Alias & mapping tangki berlaku untuk upload berikutnya. Data yang sudah ada tidak berubah; "
           "upload ulang file bulan tersebut bila perlu.")
tab_s, tab_a, tab_t, tab_u = st.tabs(["Site", "Alias ID", "Tangki fuel", "Belum terpetakan"])

with tab_s:
    with session_scope() as s:
        cur = repo.frame(s, select(m.Site.code, m.Site.name, m.Site.active, m.Site.auto_approve).order_by(m.Site.code))
    ed = st.data_editor(cur, hide_index=True, width="stretch", num_rows="dynamic", key="sites_grid",
                        column_config={"code": st.column_config.TextColumn("Kode (sesuai kolom Site Populasi)", required=True),
                                       "name": st.column_config.TextColumn("Nama", required=True),
                                       "active": st.column_config.CheckboxColumn("Aktif", default=True),
                                       "auto_approve": st.column_config.CheckboxColumn(
                                           "Auto-approve", help="Publish otomatis bila tidak ada temuan DQ kritis",
                                           default=False)})
    if st.button("Simpan site", type="primary"):
        with session_scope() as s:
            for r in ed.dropna(subset=["code"]).itertuples():
                site = s.get(m.Site, r.code) or m.Site(code=r.code)
                site.name, site.active, site.auto_approve = r.name or r.code, bool(r.active), bool(r.auto_approve)
                s.add(site)
            audit(s, user.username, "edit_sites", None, ", ".join(ed["code"].dropna()))
        st.success("Site disimpan.")

with tab_a:
    st.caption("Contoh: ID loader di timbangan tertulis 'WE030', padahal unitnya 'WEX030'.")
    with session_scope() as s:
        cur = repo.frame(s, select(m.IdAlias.alias, m.IdAlias.canonical))
    ed = st.data_editor(cur, hide_index=True, width="stretch", num_rows="dynamic", key="alias_grid",
                        column_config={"alias": st.column_config.TextColumn("ID di file", required=True),
                                       "canonical": st.column_config.TextColumn("ID sebenarnya", required=True)})
    if st.button("Simpan alias", type="primary"):
        keep = ed.dropna()
        with session_scope() as s:
            s.execute(delete(m.IdAlias))
            for r in keep.itertuples():
                s.add(m.IdAlias(alias=r.alias.strip().upper(), canonical=r.canonical.strip().upper()))
            audit(s, user.username, "edit_alias", None, f"{len(keep)} alias")
        st.success(f"{len(keep)} alias disimpan.")

with tab_t:
    with session_scope() as s:
        cur = repo.frame(s, select(m.TankSite.tank, m.TankSite.site))
        codes = list(s.scalars(select(m.Site.code)))
    ed = st.data_editor(cur, hide_index=True, width="stretch", num_rows="dynamic", key="tank_grid",
                        column_config={"tank": st.column_config.TextColumn("Unit / tangki", required=True),
                                       "site": st.column_config.SelectboxColumn("Site", options=codes, required=True)})
    if st.button("Simpan mapping tangki", type="primary"):
        keep = ed.dropna()
        with session_scope() as s:
            s.execute(delete(m.TankSite))
            for r in keep.itertuples():
                s.add(m.TankSite(tank=r.tank.strip().upper(), site=r.site))
            audit(s, user.username, "edit_tank_site", None, f"{len(keep)} tangki")
        st.success(f"{len(keep)} mapping disimpan.")

with tab_u:
    with session_scope() as s:
        rows = repo.frame(s, select(m.DQFinding.rule, m.DQFinding.unit_id, m.DQFinding.detail)
                          .where(m.DQFinding.rule.in_(["unit_tanpa_site", "loader_tanpa_site", "loader_tidak_dikenali",
                                                       "fuel_unit_tanpa_site", "tangki_tanpa_site",
                                                       "populasi_tanpa_site"])).distinct())
    if rows.empty:
        st.success("Semua ID sudah terpetakan.")
    else:
        st.caption("ID yang tidak dikenali di upload terakhir. Tambahkan alias, mapping tangki, atau lengkapi kolom "
                   "Site di Populasi Unit pada file sumber.")
        st.dataframe(rows.drop_duplicates(["rule", "unit_id"]), hide_index=True, width="stretch")
