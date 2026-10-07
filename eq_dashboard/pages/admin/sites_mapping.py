"""Sites (name, active, auto-approve), loader/DT/unit ID aliases, and fuel tank → site mapping."""
import streamlit as st
from sqlalchemy import delete, select

from core.ingest import audit
from core.ui import require
from db import models as m
from db import repo
from db.engine import session_scope

user = require("sites_mapping")
st.title("Sites & mapping")
st.caption("Aliases and tank mappings apply to the next uploads. Existing data does not change; "
           "re-upload the month's file if needed.")
tab_s, tab_a, tab_t, tab_u, tab_c = st.tabs(["Sites", "ID aliases", "Fuel tanks", "Unmapped", "Hourly cutover"])

with tab_c:
    st.markdown("From the **cutover date** on, OB and coal ritase on every dashboard and TV comes from **Hourly "
                "Production** shifts (all sites, approved or not yet); before it, from the Production Data workbook. "
                "Ritase rows of the workbook on or after the cutover are then ignored.")
    with session_scope() as s:
        cut = repo.hourly_cutover(s)
    on = st.toggle("Hourly Production is the official source of OB and coal ritase", value=cut is not None,
                   key="cut_on")
    from core.config import today_wib
    day = st.date_input("Cutover date (first production date from Hourly Production)", cut or today_wib(),
                        key="cut_date", disabled=not on, format="YYYY-MM-DD")
    new = day if on else None
    if new != cut and st.button("Save cutover", type="primary", key="cut_save"):
        with session_scope() as s:
            repo.set_setting(s, repo.CUTOVER_KEY, new.isoformat() if new else None, user.username)
            audit(s, user.username, "hourly_cutover", None, new.isoformat() if new else "off")
        st.success(f"Cutover {'set to ' + f'{new:%d %b %Y}' if new else 'switched off'}. Dashboards and TVs follow "
                   "within a minute.")

with tab_s:
    with session_scope() as s:
        cur = repo.frame(s, select(m.Site.code, m.Site.name, m.Site.active, m.Site.auto_approve).order_by(m.Site.code))
    ed = st.data_editor(cur, hide_index=True, width="stretch", num_rows="dynamic", key="sites_grid",
                        column_config={"code": st.column_config.TextColumn("Code (as in the Populasi Site column)",
                                                                           required=True),
                                       "name": st.column_config.TextColumn("Name", required=True),
                                       "active": st.column_config.CheckboxColumn("Active", default=True),
                                       "auto_approve": st.column_config.CheckboxColumn(
                                           "Auto-approve", help="Publish automatically when there are no critical "
                                                                "data quality findings", default=False)})
    if st.button("Save sites", type="primary"):
        with session_scope() as s:
            for r in ed.dropna(subset=["code"]).itertuples():
                site = s.get(m.Site, r.code) or m.Site(code=r.code)
                site.name, site.active, site.auto_approve = r.name or r.code, bool(r.active), bool(r.auto_approve)
                s.add(site)
            audit(s, user.username, "edit_sites", None, ", ".join(ed["code"].dropna()))
        st.success("Sites saved.")

with tab_a:
    st.caption("Example: the weighbridge writes loader 'WE030' while the unit is 'WEX030'.")
    with session_scope() as s:
        cur = repo.frame(s, select(m.IdAlias.alias, m.IdAlias.canonical))
    ed = st.data_editor(cur, hide_index=True, width="stretch", num_rows="dynamic", key="alias_grid",
                        column_config={"alias": st.column_config.TextColumn("ID in file", required=True),
                                       "canonical": st.column_config.TextColumn("Actual ID", required=True)})
    if st.button("Save aliases", type="primary"):
        keep = ed.dropna()
        with session_scope() as s:
            s.execute(delete(m.IdAlias))
            for r in keep.itertuples():
                s.add(m.IdAlias(alias=r.alias.strip().upper(), canonical=r.canonical.strip().upper()))
            audit(s, user.username, "edit_alias", None, f"{len(keep)} aliases")
        st.success(f"{len(keep)} aliases saved.")

with tab_t:
    with session_scope() as s:
        cur = repo.frame(s, select(m.TankSite.tank, m.TankSite.site))
        codes = list(s.scalars(select(m.Site.code)))
    ed = st.data_editor(cur, hide_index=True, width="stretch", num_rows="dynamic", key="tank_grid",
                        column_config={"tank": st.column_config.TextColumn("Unit / tank", required=True),
                                       "site": st.column_config.SelectboxColumn("Site", options=codes, required=True)})
    if st.button("Save tank mapping", type="primary"):
        keep = ed.dropna()
        with session_scope() as s:
            s.execute(delete(m.TankSite))
            for r in keep.itertuples():
                s.add(m.TankSite(tank=r.tank.strip().upper(), site=r.site))
            audit(s, user.username, "edit_tank_site", None, f"{len(keep)} tanks")
        st.success(f"{len(keep)} mappings saved.")

with tab_u:
    with session_scope() as s:
        rows = repo.frame(s, select(m.DQFinding.rule, m.DQFinding.unit_id, m.DQFinding.detail)
                          .where(m.DQFinding.rule.in_(["unit_without_site", "loader_without_site", "unknown_loader",
                                                       "fuel_unit_without_site", "tank_without_site",
                                                       "populasi_without_site"])).distinct())
    if rows.empty:
        st.success("All IDs are mapped.")
    else:
        st.caption("IDs not recognised in uploads. Add an alias or a tank mapping, or fill in the Site column of "
                   "Unit Population in the source file.")
        st.dataframe(rows.drop_duplicates(["rule", "unit_id"]), hide_index=True, width="stretch")
