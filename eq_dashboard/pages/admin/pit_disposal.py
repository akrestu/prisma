"""PIT and disposal master per site and material (OB | CG): the drop-down lists of the Hourly Production lines. A
line with trips must use an active PIT and an active disposal of its material; distances are typed on each line."""
import streamlit as st

from core import locations as LC
from core.config import UNMAPPED
from core.ingest import audit
from core.ui import refresh, require, sites_for
from db import repo
from db.engine import session_scope

user = require("haul_routes")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title("PIT & disposals")
if not sites:
    st.info("No site access.")
    st.stop()

msg = st.session_state.pop("hr_msg", None)
if msg:
    st.success(msg)
site = st.selectbox("Site", sites, key="hr_site")
with session_scope() as s:
    locs = repo.haul_locations(s, site)

st.caption("One row per PIT or disposal and material: OB → pits and disposals, CG → coal pits and ROM / stockpiles. "
           "The shift form offers the active ones; a line must use a PIT and a disposal of its material. Saved "
           "shifts keep their names, so set an old one inactive (or delete it) without changing past shifts.")
ed = st.data_editor(locs.reindex(columns=LC.COLS), num_rows="dynamic", hide_index=True, width="stretch",
                    key=f"hr_loc_{site}", column_config={
                        "kind": st.column_config.SelectboxColumn("Type", options=list(LC.KINDS), required=True,
                                                                 format_func=LC.KIND_LABEL.get, default="DISPOSAL"),
                        "name": st.column_config.TextColumn("Name", required=True, max_chars=120, width="large"),
                        "material_group": st.column_config.SelectboxColumn("Material", options=list(LC.GROUPS),
                                                                           required=True),
                        "active": st.column_config.CheckboxColumn("Active", default=True)})
if st.button("Save PIT & disposals", type="primary", key="hr_loc_save"):
    clean, problems = LC.clean(ed)
    for p in problems:
        st.error(p)
    if not problems:
        with st.spinner("Saving…"), session_scope() as s:
            n = repo.save_haul_locations(s, site, clean)
            audit(s, user.username, "haul_locations", site, f"{n} PIT / disposal rows")
        refresh("hourly")
        st.session_state["hr_msg"] = f"Saved for {site}: {n} PIT / disposal rows. New and re-saved shifts use them."
        st.rerun()
