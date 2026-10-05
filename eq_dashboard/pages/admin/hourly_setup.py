"""Load factors per site: load per trip by material × hauler model, which turns Hourly Production trips into volume
(BCM for OB, ton for coal). Edited in the grid or with the Load Factors workbook (a Mst Hourly file still works).
Targets per hour live in Hourly targets."""
import logging

import pandas as pd
import streamlit as st

from core import hourly as H
from core import load_factors as LF
from core.config import UNMAPPED, today_wib
from core.ingest import audit
from core.ui import refresh, require, sites_for
from core.validate import StructureError
from db import models as m
from db import repo
from db.engine import session_scope

COLS = ["material", "material_group", "hauler_model", "muatan"]

user = require("hourly_setup")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title("Load factors")
st.caption("Load per trip for each material × truck model: Hourly Production multiplies trips by it to get volume "
           "(BCM for OB, ton for coal). Targets per hour are set in Hourly targets.")
if not sites:
    st.info("No site access.")
    st.stop()

msg = st.session_state.pop("hs_msg", None)
if msg:
    st.success(msg)
site = st.selectbox("Site", sites, key="hs_site")
with session_scope() as s:
    lf = repo.load_factors(s, site)
    units = repo.population_for(s, today_wib())
site_units = units[units["site"] == site] if units is not None else pd.DataFrame(columns=["unit_id", "type", "model"])
hauler_units = site_units[H.is_hauler(site_units)] if len(site_units) else site_units
pop_models = sorted(hauler_units["model"].dropna().unique()) if len(hauler_units) else []
missing = [mo for mo in pop_models if mo not in set(lf["hauler_model"])]


def save_load(df: pd.DataFrame, action: str, note: str = "") -> None:
    with st.spinner("Saving load factors…"), session_scope() as s:
        n = repo.replace_site_rows(s, m.LoadFactor, site, df, COLS)
        audit(s, user.username, action, site, f"{n} rows{note}")
    refresh("hourly")
    st.session_state["hs_msg"] = f"{n} load factors saved for {site}. New and re-saved shifts use them."
    st.rerun()


t_lf, t_xls = st.tabs([f"Load factors ({len(lf)})" + (f" · {len(missing)} truck models to fill" if missing else ""),
                       "Excel"])

with t_lf:
    st.caption("The columns are the truck models of this site's unit population, so a truck's load is found from "
               "its model directly. Empty cell ('None') = that model does not carry that material.")
    grid = LF.wide(lf, pop_models)
    cols = [c for c in grid.columns if c != "material"]
    if missing and len(lf):
        st.warning(f"{len(missing)} truck model(s) of the population have no load yet: {', '.join(missing)}.")
        if st.button("Fill them from the matching models already listed", key="hs_fill"):
            filled, rep = H.expand_to_population(lf, missing)
            st.session_state["hs_fill_report"] = rep.to_dict("records")
            save_load(filled[COLS], "load_factors_fill_population")
    rep = st.session_state.pop("hs_fill_report", None)
    if rep:
        st.dataframe(pd.DataFrame(rep), hide_index=True, width="content")
    ed = st.data_editor(grid, num_rows="dynamic", hide_index=True, width="stretch", key=f"hs_lf_{site}_{len(cols)}",
                        column_config={"material": st.column_config.TextColumn("Material", required=True, width="medium"),
                                       **{c: st.column_config.NumberColumn(
                                           c, min_value=0.1, format="%.1f",
                                           help="in the unit population" if c in pop_models
                                           else "not in the unit population (general model, kept for older input)")
                                          for c in cols}})
    st.caption(f"Truck models in the population: {', '.join(pop_models) or '—'}. Extra columns at the right are "
               "general models kept for older input.")
    if st.button("Save load factors", type="primary", key="hs_lf_save"):
        new = LF.long(ed)
        bad = sorted(new.loc[new["material_group"] == "Other", "material"].unique())
        if bad:
            st.error(f"Material must start with OB or CG: {', '.join(bad)}.")
        else:
            save_load(new, "load_factors")

with t_xls:
    st.markdown(f"Download the **{LF.DATASET}** of **{site}** (one column per truck model of its population), edit "
                "it in Excel and upload it back. Uploading **replaces** the site's load factors. An old **Mst "
                f"Hourly** workbook is also accepted: its '{LF.LEGACY_SHEET}' sheet is read.")
    st.download_button(f"Download {LF.file_name(site)}", lambda: LF.build_template(site, lf, pop_models),
                       file_name=LF.file_name(site), on_click="ignore", type="primary",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    f = st.file_uploader(f"{LF.DATASET} or Mst Hourly workbook (.xlsx)", type=["xlsx", "xlsb"], max_upload_size=30,
                         key=f"hs_file_{st.session_state.get('hs_ver', 0)}")
    if f is not None:
        try:
            with st.spinner(f"Reading {f.name}…"):
                lfile = LF.parse(f.getvalue())
        except StructureError as e:
            for p in e.problems:
                st.error(p)
            st.stop()
        except Exception as e:  # unreadable file
            logging.getLogger(__name__).warning("workbook could not be opened", exc_info=True)
            st.error(f"The workbook could not be opened ({type(e).__name__}). Save it again as .xlsx and retry.")
            st.stop()
        if lfile.site and lfile.site != site:
            st.error(f"This file is for {lfile.site}; pick that site above (or download the template of {site}).")
            st.stop()
        new, rep = H.expand_to_population(lfile.load, pop_models) if lfile.site is None \
            else (lfile.load, None)
        c1, c2, c3 = st.columns(3)
        c1.metric("Load factors", len(new))
        c2.metric("Materials", new["material"].nunique())
        c3.metric("Truck models", new["hauler_model"].nunique())
        st.caption(f"Read as: {lfile.source}.")
        if rep is not None:
            st.markdown("**Truck models of the unit population** (a Mst Hourly file lists general models)")
            st.dataframe(rep, hide_index=True, width="content")
        if lfile.legacy_targets:
            st.info(f"The file also holds {lfile.legacy_targets} excavator target(s); they are not imported here. "
                    "Set targets in Hourly targets (grid or Excel).")
        if st.button(f"Replace the load factors of {site}", type="primary", key="hs_imp"):
            st.session_state["hs_ver"] = st.session_state.get("hs_ver", 0) + 1
            save_load(new[COLS], "load_factors_upload", f" from {f.name}")
