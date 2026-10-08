"""Hourly Production targets per site: per excavator model (internal and client), unit overrides, the target in
effect for every excavator with its source, and the Excel template. Separate from the Production Data defaults,
which are only the fallback here."""
import logging

import pandas as pd
import streamlit as st

from core import hourly as H
from core import hourly_targets as HT
from core import prod_target as PT
from core.config import UNMAPPED, today_wib
from core.ingest import audit
from core.ui import refresh, require, sites_for
from core.validate import StructureError
from db import models as m
from db import repo
from db.engine import session_scope

user = require("hourly_targets")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title("Hourly targets")
st.caption("Targets per production hour for Hourly Production: per excavator model of a site, with overrides for "
           "single excavators. Where none is set, the Production Data default is used and shown as 'default' "
           "(Setup → Production targets).")
if not sites:
    st.info("No site access.")
    st.stop()

msg = st.session_state.pop("ht_msg", None)
if msg:
    st.success(msg)

a, b = st.columns([1, 2])
site = a.selectbox("Site", sites, key="ht_site")
with session_scope() as s:
    models = repo.hourly_model_targets(s, site)
    over = repo.loader_targets(s, site)
    defaults = repo.model_targets(s)
    basis = repo.site_basis(s, site)
    units = repo.population_for(s, today_wib())
site_units = units[units["site"] == site] if units is not None else pd.DataFrame(columns=["unit_id", "type", "model"])
loaders = site_units[site_units["type"].fillna("").str.contains("Load", case=False)] if len(site_units) \
    else site_units
loader_models = sorted(loaders["model"].dropna().unique()) if len(loaders) else []

with b:
    new_basis = st.segmented_control("Target used for achievement", list(PT.BASIS_LABEL), default=basis,
                                     format_func=PT.BASIS_LABEL.get, key=f"ht_basis_{site}") or basis
    st.caption("Colours and achievement of this site (hourly input, TV, dashboards) use this basis; the other is "
               "kept for comparison.")
if new_basis != basis:
    with session_scope() as s:
        s.get(m.Site, site).target_basis = new_basis
        audit(s, user.username, "target_basis", site, f"{basis} -> {new_basis}")
    refresh("hourly")
    st.session_state["ht_msg"] = f"{site} now uses the {PT.BASIS_LABEL[new_basis].lower()}."
    st.rerun()


def save(models_df=None, overrides_df=None, action="hourly_targets", note="") -> None:
    with st.spinner("Saving targets…"), session_scope() as s:
        n = repo.save_hourly_targets(s, site, models_df, overrides_df)
        audit(s, user.username, action, site, ", ".join(f"{k} {v}" for k, v in n.items()) + note)
    refresh("hourly")
    st.session_state["ht_msg"] = (f"Hourly targets of {site} saved: "
                                  + ", ".join(f"{v} {k}" for k, v in n.items()) + ". New and re-saved shifts use them.")
    st.rerun()


t_eff, t_mod, t_unit, t_xls, t_apply = st.tabs(["In effect", "Per model", f"Unit overrides ({len(over)})", "Excel",
                                                "Apply to saved shifts"])

# ------------------------------------------------------------------ in effect
with t_eff:
    if loaders.empty:
        st.info(f"No excavators of {site} in the unit population.")
    else:
        rows = []
        for u in loaders.sort_values("unit_id").itertuples():
            row = {"Excavator": u.unit_id, "Model": u.model}
            for label, mat in (("OB", "OB - FreeDig"), ("Mud", "OB - MUD"), ("Coal", "CG - Coal Getting")):
                v, src = PT.hourly_target(u.unit_id, u.model, mat, basis, over, models, defaults)
                row[label] = v
                row[f"{label} source"] = PT.SOURCE_LABEL.get(src, "none")
            rows.append(row)
        eff = pd.DataFrame(rows)
        n_def = int((eff[["OB source", "Coal source"]] == PT.SOURCE_LABEL[PT.DEFAULT]).any(axis=1).sum())
        st.markdown(f"**Target per hour for each excavator of {site}** · {PT.BASIS_LABEL[basis].lower()}")
        if n_def:
            st.warning(f"{n_def} excavator(s) use the Production Data default because no hourly target is set. "
                       "Add their model in **Per model** to give them an hourly target.")
        st.dataframe(eff, hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(c, format="%.0f") for c in ("OB", "Mud", "Coal")})
        st.caption("Order: unit override → hourly target of the model → Production Data default. Shifts keep the "
                   "target they were saved with; save a shift again to apply a new target to it.")

# ------------------------------------------------------------------ per model
with t_mod:
    grid = PT.wide(models, HT.MODEL_VALUES)
    extra = [mo for mo in loader_models if PT.match(mo, grid["model"]) is None]
    if extra:
        grid = PT.numeric(pd.concat([grid, pd.DataFrame({"model": extra})], ignore_index=True))
    for bsis in PT.BASES:
        grid[f"Default OB · {bsis}"] = pd.to_numeric([PT.model_target(mo, "OB", defaults, bsis)
                                                      for mo in grid["model"]], errors="coerce")
    st.caption("One row per excavator model of the site (a model name also covers longer unit models, e.g. "
               "'SK520' covers SK520XDLC-10). Empty ('None') = use the Production Data default (grey, read-only).")
    num = lambda lbl: st.column_config.NumberColumn(lbl, min_value=0, format="%.0f")  # noqa: E731
    ed = st.data_editor(grid, num_rows="dynamic", hide_index=True, width="stretch", key=f"ht_models_{site}",
                        disabled=[f"Default OB · {b_}" for b_ in PT.BASES],
                        column_config={"model": st.column_config.TextColumn("Model", required=True),
                                       **{c: num(c) for c in grid.columns if c != "model"}})
    if st.button("Save model targets", type="primary", key="ht_models_save"):
        save(models_df=PT.long(ed, HT.MODEL_VALUES), action="hourly_model_targets")

# ------------------------------------------------------------------ unit overrides
with t_unit:
    st.caption("Only where one excavator differs from its model. Coal is the target in t/h.")
    ed_u = st.data_editor(over, num_rows="dynamic", hide_index=True, width="stretch", key=f"ht_units_{site}",
                          column_config={
                              "unit_id": st.column_config.TextColumn("Excavator", required=True),
                              "model": st.column_config.TextColumn("Model"),
                              "material_group": st.column_config.SelectboxColumn("Material", options=["OB", "CG"],
                                                                                 required=True, default="OB"),
                              "basis": st.column_config.SelectboxColumn("Basis", options=list(PT.BASES),
                                                                        required=True, default=basis),
                              "target_per_hour": st.column_config.NumberColumn("Target per hour", min_value=0,
                                                                               format="%.0f", required=True)})
    if st.button("Save unit overrides", type="primary", key="ht_units_save"):
        e = ed_u.dropna(subset=["unit_id", "material_group", "basis", "target_per_hour"]).copy()
        e["unit_id"] = H._ids(e["unit_id"])
        model_of = dict(zip(loaders["unit_id"], loaders["model"], strict=True)) if len(loaders) else {}
        e["model"] = e["model"].fillna(e["unit_id"].map(model_of))
        if e.duplicated(["unit_id", "material_group", "basis"]).any():
            st.error("Each excavator may have one target per material (OB / CG) and basis.")
        else:
            save(overrides_df=e, action="hourly_unit_targets")

# ------------------------------------------------------------------ Excel
with t_xls:
    st.markdown(f"Download the targets of **{site}** (every excavator model of the site is listed, with the "
                "Production Data default for reference), edit them in Excel and upload the file back. Uploading "
                "**replaces** the site's model targets and unit overrides.")
    st.download_button(f"Download {HT.file_name(site)}",
                       lambda: HT.build_template(site, models, over, defaults, loader_models),
                       file_name=HT.file_name(site), on_click="ignore", type="primary",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    f = st.file_uploader("Filled targets workbook (.xlsx)", type=["xlsx"], max_upload_size=10,
                         key=f"ht_file_{st.session_state.get('ht_ver', 0)}")
    if f is not None:
        try:
            with st.spinner(f"Reading {f.name}…"):
                tf = HT.parse_template(f.getvalue())
        except StructureError as e:
            for p_ in e.problems:
                st.error(p_)
            st.stop()
        except Exception as e:  # unreadable file
            logging.getLogger(__name__).warning("workbook could not be opened", exc_info=True)
            st.error(f"The workbook could not be opened ({type(e).__name__}). Save it again as .xlsx and retry.")
            st.stop()
        if tf.site != site:
            st.error(f"This file is for {tf.site}; pick that site above (or download the template of {site}).")
            st.stop()
        c1, c2 = st.columns(2)
        c1.metric("Model targets", len(tf.models))
        c2.metric("Unit overrides", len(tf.overrides))
        for p_ in tf.problems:
            st.error(p_)
        with st.expander("Show the targets in the file"):
            st.dataframe(tf.models, hide_index=True, width="stretch")
            st.dataframe(tf.overrides, hide_index=True, width="stretch")
        if not tf.problems and st.button(f"Replace the hourly targets of {site}", type="primary", key="ht_xsave"):
            st.session_state["ht_ver"] = st.session_state.get("ht_ver", 0) + 1
            save(tf.models, tf.overrides, "hourly_targets_upload", f" from {f.name}")

# ------------------------------------------------------------------ apply to saved shifts
with t_apply:
    st.markdown(f"A saved shift keeps the target it was saved with. After changing targets, apply them to the "
                f"shifts of **{site}** already saved in a date range (hourly input, dashboard and TV then use them).")
    today = today_wib()
    rng = st.date_input("Production dates", (today.replace(day=1), today), key=f"ht_apply_{site}",
                        format="DD/MM/YYYY")
    if isinstance(rng, (list, tuple)) and len(rng) == 2 and st.button("Apply current targets", type="primary",
                                                                      key="ht_apply_go"):
        with st.spinner("Recalculating targets of the saved shifts…"), session_scope() as s:
            n = repo.recalc_hourly_targets(s, site, rng[0], rng[1])
            audit(s, user.username, "hourly_targets_apply", site,
                  f"{rng[0]:%Y-%m-%d}..{rng[1]:%Y-%m-%d}: {n['changed']} of {n['lines']} lines in {n['shifts']} shifts")
        refresh("hourly")
        st.session_state["ht_msg"] = (f"{n['shifts']} shift(s) of {site} checked: {n['changed']} of {n['lines']} "
                                      "line(s) got a new target.")
        st.rerun()
