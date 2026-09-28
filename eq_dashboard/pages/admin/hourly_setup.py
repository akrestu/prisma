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
    mmap = repo.hauler_model_map(s, site)
    units = repo.population_for(s, today_wib())
site_units = units[units["site"] == site] if units is not None else pd.DataFrame(columns=["unit_id", "type", "model"])
hauler_units = site_units[H.is_hauler(site_units)] if len(site_units) else site_units
lf_models = sorted(lf["hauler_model"].unique()) if len(lf) else []
models = (hauler_units.groupby("model")["unit_id"].agg(["count", lambda x: ", ".join(sorted(x)[:6])])
          .set_axis(["units", "examples"], axis=1).reset_index()) if len(hauler_units) else pd.DataFrame()
unmatched = [mo for mo in (models["model"] if len(models) else []) if H.load_model(mo, lf_models, {
    k.upper(): v for k, v in mmap.items()}) is None]

t_lf, t_tg, t_map, t_imp = st.tabs([f"Load factors ({len(lf)})", f"Hourly targets ({len(tg)})",
                                    "Hauler models" + (f" ({len(unmatched)} to map)" if unmatched else ""),
                                    "Import from Mst Hourly"])

with t_lf:
    st.caption("One row per material × hauler model. The material must start with OB or CG.")
    ed = st.data_editor(lf[["material", "hauler_model", "muatan"]], num_rows="dynamic", hide_index=True,
                        width="stretch", key=f"hs_lf_{site}",
                        column_config={"material": st.column_config.TextColumn("Material", required=True),
                                       "hauler_model": st.column_config.TextColumn("Hauler model", required=True),
                                       "muatan": st.column_config.NumberColumn("Load per trip", min_value=0.1,
                                                                               format="%.1f", required=True)})
    if st.button("Save load factors", type="primary", key="hs_lf_save"):
        e = ed.dropna(subset=["material", "hauler_model", "muatan"]).copy()
        e["material"], e["hauler_model"] = e["material"].str.strip(), e["hauler_model"].str.strip().str.upper()
        e["material_group"] = H.material_group(e["material"]).to_numpy()
        bad = e[e["material_group"] == "Other"]
        dup = e[e.duplicated(["material", "hauler_model"], keep=False)]
        if len(bad):
            st.error(f"Material must start with OB or CG: {', '.join(sorted(bad['material'].unique()))}.")
        elif len(dup):
            st.error("Each material × hauler model may appear only once.")
        else:
            with session_scope() as s:
                n = repo.replace_site_rows(s, m.LoadFactor, site, e,
                                           ["material", "material_group", "hauler_model", "muatan"])
                audit(s, user.username, "hourly_load_factors", site, f"{n} rows")
            st.cache_data.clear()
            st.session_state["hs_msg"] = f"{n} load factors saved for {site}."
            st.rerun()
    if len(lf):
        st.markdown("**Matrix view**")
        st.dataframe(lf.pivot_table(index="material", columns="hauler_model", values="muatan"), width="stretch")

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

with t_map:
    st.caption("Each hauler model in the unit population needs a load class from the load factors. Names that "
               "match exactly or after dropping the unit suffix ('777E-KDP' → '777E') are found automatically; "
               "map the others here (e.g. CWE37064R → CWE370Q).")
    if models.empty:
        st.info("No hauling units in the unit population of this site.")
    elif not lf_models:
        st.info("Add load factors first.")
    else:
        up = {k.upper(): v for k, v in mmap.items()}
        view = models.assign(
            auto=[H.load_model(mo, lf_models) for mo in models["model"]],
            load_model=[up.get(str(mo).upper()) or H.load_model(mo, lf_models) or H.suggest_load_model(mo, lf_models)
                        for mo in models["model"]])
        view["how"] = ["mapped" if str(mo).upper() in up else ("automatic" if a else "suggested — check")
                       for mo, a in zip(view["model"], view["auto"], strict=True)]
        ed = st.data_editor(view[["model", "units", "examples", "how", "load_model"]], hide_index=True,
                            width="stretch", key=f"hs_map_{site}", disabled=["model", "units", "examples", "how"],
                            column_config={
                                "model": st.column_config.TextColumn("Hauler model (population)"),
                                "units": st.column_config.NumberColumn("Units"),
                                "examples": st.column_config.TextColumn("Units (first 6)"),
                                "how": st.column_config.TextColumn("Match"),
                                "load_model": st.column_config.SelectboxColumn("Load class", options=lf_models)})
        if st.button("Save hauler models", type="primary", key="hs_map_save"):
            keep = ed[ed["load_model"].notna()].merge(view[["model", "auto"]], on="model")
            # store only what the automatic rule would not find by itself
            keep = keep[keep["load_model"] != keep["auto"]].rename(columns={"model": "unit_model"})
            with session_scope() as s:
                n = repo.replace_site_rows(s, m.HaulerModelMap, site, keep, ["unit_model", "load_model"])
                audit(s, user.username, "hourly_model_map", site, f"{n} mappings")
            st.cache_data.clear()
            st.session_state["hs_msg"] = f"Hauler models saved for {site} ({n} manual mappings)."
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
        c1, c2 = st.columns(2)
        c1.metric("Load factors", len(new_lf))
        c2.metric("Excavator targets", len(new_tg))
        st.dataframe(new_lf.pivot_table(index="material", columns="hauler_model", values="muatan"), width="stretch")
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
