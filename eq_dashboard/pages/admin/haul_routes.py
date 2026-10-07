"""Destinations (Tujuan) and routes per site: where haulers unload, and for each loader + destination the loading pit
and the horizontal / vertical haul distance, valid from a date until replaced. Hourly Production lines pick a
destination; pit and distances are filled from the route. Edited in the grid or with the Haul Routes workbook."""
import logging

import pandas as pd
import streamlit as st

from core import routes as RT
from core.config import UNMAPPED, today_wib
from core.ingest import audit
from core.ui import refresh, require, sites_for
from core.validate import StructureError
from db import repo
from db.engine import session_scope

user = require("haul_routes")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title("Destinations & routes")
st.caption("Where haulers unload (Tujuan), and per loader + destination the loading pit and haul distances. The "
           "shift form only asks for the destination; pit and distances come from the route in force that day.")
if not sites:
    st.info("No site access.")
    st.stop()

msg = st.session_state.pop("hr_msg", None)
if msg:
    st.success(msg)
site = st.selectbox("Site", sites, key="hr_site")
today = today_wib()
with session_scope() as s:
    dest = repo.haul_destinations(s, site)
    routes = repo.haul_routes(s, site)
    tg = repo.loader_targets(s, site)
    units = repo.population_for(s, today)
site_units = units[units["site"] == site] if units is not None else pd.DataFrame(columns=["unit_id", "type"])
loaders = sorted(set(tg["unit_id"]) | set(site_units.loc[site_units["type"].fillna("")
                                                          .str.contains("Load", case=False), "unit_id"]))


def save(destinations=None, new_routes=None, action="haul_routes", note="") -> None:
    with st.spinner("Saving…"), session_scope() as s:
        n = repo.save_haul_setup(s, site, destinations, new_routes)
        audit(s, user.username, action, site, ", ".join(f"{v} {k}" for k, v in n.items()) + note)
    refresh("hourly")
    st.session_state["hr_msg"] = (f"Saved for {site}: " + ", ".join(f"{v} {k}" for k, v in n.items())
                                  + ". New and re-saved shifts use them.")
    st.rerun()


shown = RT.current(routes, today)
t_dest, t_route, t_xls = st.tabs([f"Destinations ({len(dest)})", f"Routes ({len(shown)})", "Excel"])

with t_dest:
    st.caption("OB → disposals, CG → ROM / stockpiles. A destination already used by a route is never deleted: "
               "set it inactive to hide it from the shift form.")
    ed = st.data_editor(dest.reindex(columns=RT.DEST_COLS), num_rows="dynamic", hide_index=True, width="stretch",
                        key=f"hr_dest_{site}", column_config={
                            "name": st.column_config.TextColumn("Destination", required=True, max_chars=120,
                                                                width="large"),
                            "material_group": st.column_config.SelectboxColumn("Material", options=list(RT.GROUPS),
                                                                               required=True),
                            "active": st.column_config.CheckboxColumn("Active", default=True)})
    if st.button("Save destinations", type="primary", key="hr_dest_save"):
        clean, problems = RT.clean_destinations(ed)
        for p in problems:
            st.error(p)
        if not problems:
            save(destinations=clean, action="haul_destinations")

with t_route:
    if dest.empty:
        st.info("Add the destinations first.")
    else:
        st.caption(f"Routes in force today ({today:%d %b %Y}) and planned ones. To change a distance from a date, "
                   "add a row with the same loader and destination and that 'Valid from': shifts before it keep the "
                   "old distance. Routes already replaced stay stored for older shifts.")
        grid = shown.reindex(columns=RT.ROUTE_COLS).copy()
        grid["valid_from"] = pd.to_datetime(grid["valid_from"]).dt.date
        er = st.data_editor(grid, num_rows="dynamic", hide_index=True, width="stretch", key=f"hr_route_{site}",
                            column_config={
                                "loader": st.column_config.SelectboxColumn("Loader", options=loaders, required=True),
                                "destination": st.column_config.SelectboxColumn(
                                    "Destination", options=sorted(dest["name"]), required=True, width="medium"),
                                "pit": st.column_config.TextColumn("PIT", max_chars=120),
                                "dist_h": st.column_config.NumberColumn("Horizontal (m)", min_value=0,
                                                                        max_value=50_000, step=50, format="%.0f"),
                                "dist_v": st.column_config.NumberColumn("Vertical (m)", min_value=0,
                                                                        max_value=50_000, step=5, format="%.0f"),
                                "valid_from": st.column_config.DateColumn("Valid from", format="YYYY-MM-DD",
                                                                          default=today)})
        if st.button("Save routes", type="primary", key="hr_route_save"):
            clean, problems = RT.clean_routes(er, dest, today)
            for p in problems:
                st.error(p)
            if not problems:
                save(new_routes=RT.merge_routes(routes, clean, today), action="haul_routes")

with t_xls:
    st.markdown(f"Download the **{RT.DATASET}** of **{site}** (sheets Destinations and Routes), edit it in Excel and "
                "upload it back. Uploading **replaces** the destinations and the routes in force today and later; "
                "routes already replaced stay stored for older shifts.")
    st.download_button(f"Download {RT.file_name(site)}", lambda: RT.build_template(site, dest, shown, loaders),
                       file_name=RT.file_name(site), on_click="ignore", type="primary",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    f = st.file_uploader(f"{RT.DATASET} workbook (.xlsx)", type=["xlsx"], max_upload_size=10,
                         key=f"hr_file_{st.session_state.get('hr_ver', 0)}")
    if f is not None:
        try:
            with st.spinner(f"Reading {f.name}…"):
                rf = RT.parse(f.getvalue(), today)
        except StructureError as e:
            for p in e.problems:
                st.error(p)
            st.stop()
        except Exception as e:  # unreadable file
            logging.getLogger(__name__).warning("workbook could not be opened", exc_info=True)
            st.error(f"The workbook could not be opened ({type(e).__name__}). Save it again as .xlsx and retry.")
            st.stop()
        if rf.site and rf.site != site:
            st.error(f"This file is for {rf.site}; pick that site above (or download the template of {site}).")
            st.stop()
        c1, c2 = st.columns(2)
        c1.metric("Destinations", len(rf.destinations))
        c2.metric("Routes", len(rf.routes))
        for p in rf.problems:
            st.error(p)
        if not rf.problems and st.button(f"Replace destinations and routes of {site}", type="primary",
                                         key="hr_imp"):
            st.session_state["hr_ver"] = st.session_state.get("hr_ver", 0) + 1
            save(rf.destinations, RT.merge_routes(routes, rf.routes, today), "haul_routes_upload",
                 f" from {f.name}")
