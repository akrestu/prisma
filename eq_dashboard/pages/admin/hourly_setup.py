"""Hourly setup per site: load factors (material × hauler model) and hourly targets per excavator."""
import pandas as pd
import streamlit as st

from core import hourly as H
from core.config import UNMAPPED, today_wib
from core.ingest import audit
from core.ui import require, sites_for
from core.validate import StructureError
from db import models as m
from db import repo
from db.engine import session_scope

user = require("hourly_setup")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title("Hourly setup")
st.caption("Load per trip and hourly targets used by Hourly input and the hourly production TV screen. "
           "Volume = trips × load: BCM for OB, ton for coal.")
if not sites:
    st.info("No site access.")
    st.stop()

msg = st.session_state.pop("hs_msg", None)
if msg:
    st.success(msg)
site = st.selectbox("Site", sites, key="hs_site")
with session_scope() as s:
    lf = repo.load_factors(s, site)
    tg = repo.loader_targets(s, site)
    units = repo.population_for(s, today_wib())
site_units = units[units["site"] == site] if units is not None else pd.DataFrame(columns=["unit_id", "type", "model"])
hauler_units = site_units[H.is_hauler(site_units)] if len(site_units) else site_units
pop_models = sorted(hauler_units["model"].dropna().unique()) if len(hauler_units) else []
missing = [mo for mo in pop_models if mo not in set(lf["hauler_model"])]


def save_load(df: pd.DataFrame, action: str) -> None:
    e = df.dropna(subset=["material", "hauler_model", "muatan"]).copy()
    e["material"], e["hauler_model"] = e["material"].str.strip(), e["hauler_model"].str.strip()
    e["material_group"] = H.material_group(e["material"]).to_numpy()
    bad = e[e["material_group"] == "Other"]
    if len(bad):
        st.error(f"Material must start with OB or CG: {', '.join(sorted(bad['material'].unique()))}.")
        return
    e = e.drop_duplicates(["material", "hauler_model"], keep="last")
    with session_scope() as s:
        n = repo.replace_site_rows(s, m.LoadFactor, site, e, ["material", "material_group", "hauler_model", "muatan"])
        audit(s, user.username, action, site, f"{n} rows")
    st.cache_data.clear()
    st.session_state["hs_msg"] = f"{n} load factors saved for {site}."
    st.rerun()


t_lf, t_tg, t_imp = st.tabs([f"Load factors ({len(lf)})" + (f" · {len(missing)} truck models to fill" if missing
                                                             else ""), f"Hourly targets ({len(tg)})",
                             "Import from Mst Hourly"])

with t_lf:
    st.caption("Load per trip for each material × truck model. The columns are the truck models of this site's "
               "unit population, so a truck's load is found from its model directly. Empty cell = that model does "
               "not carry that material.")
    cols = pop_models + [mo for mo in sorted(lf["hauler_model"].unique()) if mo not in pop_models] if len(lf)         else pop_models
    wide = (lf.pivot_table(index="material", columns="hauler_model", values="muatan", aggfunc="first")
            .reindex(columns=cols) if len(lf) else pd.DataFrame(columns=cols, index=pd.Index([], name="material")))
    wide = wide.reset_index()
    if missing and len(lf):
        st.warning(f"{len(missing)} truck model(s) of the population have no load yet: {', '.join(missing)}.")
        if st.button("Fill them from the matching Link Muatan models", key="hs_fill"):
            filled, rep = H.expand_to_population(lf, missing)
            st.session_state["hs_fill_report"] = rep.to_dict("records")
            save_load(filled, "hourly_load_fill_population")
    rep = st.session_state.pop("hs_fill_report", None)
    if rep:
        st.dataframe(pd.DataFrame(rep), hide_index=True, width="content")
    ed = st.data_editor(wide, num_rows="dynamic", hide_index=True, width="stretch", key=f"hs_lf_{site}_{len(cols)}",
                        column_config={"material": st.column_config.TextColumn("Material", required=True, width="medium"),
                                       **{c: st.column_config.NumberColumn(
                                           c, min_value=0.1, format="%.1f",
                                           help="in the unit population" if c in pop_models
                                           else "not in the unit population (general model from Link Muatan)")
                                          for c in cols}})
    st.caption(f"Truck models in the population: {', '.join(pop_models) or '—'}. Extra columns at the right are "
               "general models from Link Muatan, kept for older input.")
    if st.button("Save load factors", type="primary", key="hs_lf_save"):
        long = ed.melt(id_vars=["material"], var_name="hauler_model", value_name="muatan")
        save_load(long, "hourly_load_factors")

with t_tg:
    st.caption("Target per excavator per hour: BCM/h for OB, t/h for coal (CG).")
    ed = st.data_editor(tg, num_rows="dynamic", hide_index=True, width="stretch", key=f"hs_tg_{site}",
                        column_config={
                            "unit_id": st.column_config.TextColumn("Excavator", required=True),
                            "model": st.column_config.TextColumn("Model"),
                            "material_group": st.column_config.SelectboxColumn("Material", options=["OB", "CG"],
                                                                               required=True, default="OB"),
                            "target_per_hour": st.column_config.NumberColumn("Target per hour", min_value=0,
                                                                             format="%.0f", required=True)})
    if st.button("Save targets", type="primary", key="hs_tg_save"):
        e = ed.dropna(subset=["unit_id", "material_group", "target_per_hour"]).copy()
        e["unit_id"] = H._ids(e["unit_id"])
        if e.duplicated(["unit_id", "material_group"]).any():
            st.error("Each excavator may have one target per material (OB / CG).")
        else:
            with session_scope() as s:
                n = repo.replace_site_rows(s, m.LoaderTarget, site, e,
                                           ["unit_id", "model", "material_group", "target_per_hour"])
                audit(s, user.username, "hourly_targets", site, f"{n} rows")
            st.cache_data.clear()
            st.session_state["hs_msg"] = f"{n} hourly targets saved for {site}."
            st.rerun()

with t_imp:
    st.markdown("Read the **Link Muatan** sheet of the Mst Hourly workbook: the load matrix (material × hauler "
                "model) and the target per excavator. Imported targets are OB targets; add coal targets in the "
                "Hourly targets tab.")
    f = st.file_uploader("Mst Hourly workbook (.xlsx)", type=["xlsx", "xlsb"], key="hs_file", max_upload_size=30)
    if f is not None:
        try:
            new_lf, new_tg = H.parse_link_muatan(f.getvalue())
        except StructureError as e:
            for p in e.problems:
                st.error(p)
            st.stop()
        new_tg = new_tg.assign(material_group="OB")
        new_lf, rep = H.expand_to_population(new_lf, pop_models)
        c1, c2 = st.columns(2)
        c1.metric("Load factors", len(new_lf))
        c2.metric("Excavator targets", len(new_tg))
        st.markdown("**Truck models of the unit population**")
        st.dataframe(rep, hide_index=True, width="content")
        keep_cg = tg[tg["material_group"] == "CG"]
        st.caption(f"Replaces all load factors and OB targets of {site}"
                   + (f"; its {len(keep_cg)} coal target(s) are kept." if len(keep_cg) else "."))
        if st.button("Import into " + site, type="primary", key="hs_imp"):
            with session_scope() as s:
                repo.replace_site_rows(s, m.LoadFactor, site, new_lf,
                                       ["material", "material_group", "hauler_model", "muatan"])
                repo.replace_site_rows(s, m.LoaderTarget, site, pd.concat([new_tg, keep_cg], ignore_index=True),
                                       ["unit_id", "model", "material_group", "target_per_hour"])
                audit(s, user.username, "hourly_import_link_muatan", site,
                      f"{len(new_lf)} load factors, {len(new_tg)} targets from {f.name}")
            st.cache_data.clear()
            st.session_state["hs_msg"] = f"Imported {len(new_lf)} load factors and {len(new_tg)} targets into {site}."
            st.rerun()
