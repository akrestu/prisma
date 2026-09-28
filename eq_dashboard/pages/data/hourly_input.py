"""Hourly input: trips per excavator × hauler per hour for one site and shift (web grid or Excel template).

Flash data: saved immediately without approval and shown on the hourly production TV screen within a minute.
"""
import pandas as pd
import streamlit as st

from core import hourly as H
from core.config import UNMAPPED, WIB, now_wib
from core.ingest import audit
from core.ui import fmt_num, require, sites_for
from core.validate import StructureError
from db import repo
from db.engine import session_scope

user = require("hourly_input")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title("Hourly input")
if not sites:
    st.info("No site access.")
    st.stop()

msg = st.session_state.pop("hi_msg", None)
if msg:
    st.success(msg)

p_date, p_shift, p_slot = H.production_hour(now_wib())
goto = st.session_state.pop("hi_goto", None)   # after an upload: open the shift that was just saved
if goto:
    st.session_state["hi_site"], st.session_state["hi_date"], st.session_state["hi_shift"] = goto
a, b, c = st.columns([1.2, 1, 1])
site = a.selectbox("Site", sites, key="hi_site")
date = b.date_input("Production date", p_date, key="hi_date",
                    help="The production day starts at 06:00; the night shift after midnight belongs to the date before")
shift = c.segmented_control("Shift", list(H.SHIFTS), default=p_shift, key="hi_shift") or p_shift
if (date, shift) == (p_date, p_shift):
    st.caption(f"Current hour: **{H.slot_label(shift, p_slot)}** (WIB). Trips are counted per production hour.")

with session_scope() as s:
    lf = repo.load_factors(s, site)
    tg = repo.loader_targets(s, site)
    sh, rows = repo.hourly_shift(s, site, date, shift)
    prev = repo.previous_lines(s, site, date, shift) if sh is None else None
    units = repo.population_for(s, date)
    ops = repo.operators(s, site)
    mtg, basis = repo.model_targets(s), repo.site_basis(s, site)
    coord_now = sh.coordinator if sh else ""
    stamp = f"{sh.updated_by} · {sh.updated_at.astimezone(WIB):%d %b %H:%M} WIB" if sh else ""
if lf.empty:
    st.warning(f"No load factors for {site} yet. An Admin or Site Manager sets them in **Admin → Hourly setup**.")
    st.stop()

site_units = units[units["site"] == site] if units is not None else pd.DataFrame(columns=["unit_id", "type"])
is_type = lambda word: site_units["type"].fillna("").str.contains(word, case=False)  # noqa: E731
loaders = sorted(set(tg["unit_id"]) | set(site_units.loc[is_type("Load"), "unit_id"]))
haulers = sorted(site_units.loc[H.is_hauler(site_units), "unit_id"]) if len(site_units) else []
op_label = {n: f"{n} - {nm}" for n, nm in zip(ops["nrp"], ops["name"], strict=True)}
code_label = {k: f"{k} - {v}" for k, v in H.REMARKS.items()}
slots = H.SLOTS[shift]
GRID = ["loader", "loader_nrp", "material", "hauler", "hauler_model", "hauler_nrp", "pit", "disposal", "distance_m",
        *H.R, "remark_code", "remark"]
unit_model = dict(zip(site_units["unit_id"], site_units["model"], strict=True)) if len(site_units) else {}


def to_grid(df: pd.DataFrame) -> pd.DataFrame:
    g = df.reindex(columns=GRID).copy()
    g["remark_code"] = g["remark_code"].map(lambda x: code_label.get(str(x), x) if pd.notna(x) else None)
    for c in ("loader_nrp", "hauler_nrp"):
        g[c] = g[c].map(lambda x: op_label.get(str(x), x) if pd.notna(x) else None)
    if "operator" in df:                                   # old lines carry a name instead of an NRP
        g["loader_nrp"] = g["loader_nrp"].fillna(df["operator"])
    g["hauler_model"] = g["hauler"].map(unit_model).fillna(g["hauler_model"])
    return g


def from_grid(g: pd.DataFrame) -> pd.DataFrame:
    out = g.copy()
    out["remark_code"] = out["remark_code"].astype("string").str.extract(r"^(\d{3})", expand=False)
    return out


t_web, t_xls = st.tabs(["Web input", "Excel template"])

# ------------------------------------------------------------------ web grid
with t_web:
    base = rows if sh is not None else (prev if prev is not None and len(prev) else pd.DataFrame(columns=GRID))
    if sh is None and prev is not None and len(prev):
        st.caption("New shift: lines copied from the previous shift (no trips). Change or delete what differs.")
    legacy = base[base["hauler"].isna() & base["hauler_model"].notna()] if len(base) and "hauler" in base else []
    if len(legacy):
        st.warning(f"{len(legacy)} line(s) come from the old format: one line per hauler **model**, without a "
                   "Hauler ID. Replace each with one line per truck (Hauler ID + its operator) so trips can be "
                   "counted per operator.")
    elif sh is not None:
        st.caption(f"Last saved by {stamp}.")
    coord = st.text_input("Shift boss", coord_now, key=f"hi_coord_{site}_{date}_{shift}",
                          help="Shown in the header of the hourly TV screen")
    ver = st.session_state.get("hi_ver", 0)
    if ops.empty:
        st.caption("⚠ No operators for this site yet: add them in **Admin → Operators** to pick them by NRP.")
    cfg = {
        "loader": st.column_config.SelectboxColumn("Excavator", options=loaders, required=True),
        "loader_nrp": st.column_config.SelectboxColumn("Operator", options=list(op_label.values()),
                                                       width="medium"),
        "material": st.column_config.SelectboxColumn("Material", options=sorted(lf["material"].unique()),
                                                     required=True),
        "hauler": st.column_config.SelectboxColumn("Hauler ID", options=haulers, required=True),
        "hauler_model": st.column_config.TextColumn("Hauler model", disabled=True,
                                                    help="From the unit population after saving; not typed"),
        "hauler_nrp": st.column_config.SelectboxColumn("Hauler operator", options=list(op_label.values()),
                                                       width="medium"),
        "pit": st.column_config.TextColumn("PIT"),
        "disposal": st.column_config.TextColumn("Disposal"),
        "distance_m": st.column_config.NumberColumn("Distance (m)", min_value=0, step=50, format="%.0f"),
        **{r: st.column_config.NumberColumn(lbl, min_value=0, max_value=20, step=1, format="%d", width="small")
           for r, lbl in zip(H.R, slots, strict=True)},
        "remark_code": st.column_config.SelectboxColumn("Remark code", options=list(code_label.values())),
        "remark": st.column_config.TextColumn("Remark", width="large"),
    }
    grid = st.data_editor(to_grid(base), num_rows="dynamic", hide_index=True, width="stretch", column_config=cfg,
                          key=f"hi_grid_{site}_{date}_{shift}_{ver}", height=min(600, 38 * (len(base) + 3) + 40))
    res = H.resolve(from_grid(grid), lf, tg, units, ops, model_targets=mtg, basis=basis)
    st.caption("One row per hauler. When a hauler's operator changes during the shift, add a second row for the "
               "same hauler with the new operator.")
    for w in res.warnings:
        st.caption(f"⚠ {w}")
    if len(res.rows) and not res.problems:
        long = H.to_long(res.rows.assign(site=site, date=date, shift=shift))
        tot = long.groupby("material_group")["volume"].sum()
        k = st.columns(5)
        k[0].metric("OB (BCM)", fmt_num(tot.get("OB", 0)))
        k[1].metric("Coal (t)", fmt_num(tot.get("CG", 0), 1))
        k[2].metric("Trips", fmt_num(long["rit"].sum()))
        k[3].metric("Fleets", res.rows["loader"].nunique())
        k[4].metric("Haulers", res.rows["hauler"].nunique())
    if st.button("Save shift", type="primary", key="hi_save"):
        if res.problems:
            for p in res.problems:
                st.error(p)
        else:
            with session_scope() as s:
                repo.save_hourly(s, site, date, shift, coord, res.rows, user.username, "web")
                audit(s, user.username, "hourly_save", site, f"{date:%Y-%m-%d} {shift}: {len(res.rows)} lines")
            st.cache_data.clear()
            st.session_state["hi_ver"] = ver + 1
            st.session_state["hi_msg"] = f"{site} {date:%d %b} {shift} saved ({len(res.rows)} lines)."
            st.rerun()

# ------------------------------------------------------------------ Excel template
with t_xls:
    st.markdown("For bulk entry or when the connection is poor: download the template for this site and shift, "
                "fill in the trips in Excel, then upload it here. Uploading **replaces** the shift.")
    lines = rows if sh is not None else (prev if prev is not None else None)
    st.download_button(f"Download template · {site} {date:%d %b} {shift}",
                       lambda: H.build_template(site, date, shift, lf, tg, lines, coord_now, units, ops),
                       file_name=f"Hourly_{site}_{date:%Y-%m-%d}_{shift}.xlsx", on_click="ignore",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    f = st.file_uploader("Filled template (.xlsx)", type=["xlsx"], key=f"hi_file_{st.session_state.get('hi_ver', 0)}",
                         max_upload_size=10)
    if f is not None:
        try:
            hf = H.parse_template(f.getvalue())
        except StructureError as e:
            for p in e.problems:
                st.error(p)
            st.stop()
        if hf.site not in sites:
            st.error(f"The file is for site {hf.site}, which you do not have access to.")
            st.stop()
        with session_scope() as s:
            lf_f, tg_f = repo.load_factors(s, hf.site), repo.loader_targets(s, hf.site)
            exists, _ = repo.hourly_shift(s, hf.site, hf.date, hf.shift)
            units_f = repo.population_for(s, hf.date)
            ops_f = repo.operators(s, hf.site)
            mtg_f, basis_f = repo.model_targets(s), repo.site_basis(s, hf.site)
        rf = H.resolve(hf.rows, lf_f, tg_f, units_f, ops_f, model_targets=mtg_f, basis=basis_f)
        st.markdown(f"**{hf.site} · {hf.date:%d %b %Y} · {hf.shift}** · {len(rf.rows)} lines"
                    + (f" · coordinator {hf.coordinator}" if hf.coordinator else ""))
        for p in rf.problems:
            st.error(p)
        for w in rf.warnings:
            st.caption(f"⚠ {w}")
        if exists is not None:
            st.warning("This shift already has data; saving replaces it.")
        if not rf.problems and st.button("Save uploaded shift", type="primary", key="hi_xsave"):
            with session_scope() as s:
                repo.save_hourly(s, hf.site, hf.date, hf.shift, hf.coordinator, rf.rows, user.username, "excel")
                audit(s, user.username, "hourly_upload", hf.site,
                      f"{hf.date:%Y-%m-%d} {hf.shift}: {len(rf.rows)} lines from {f.name}")
            st.cache_data.clear()
            lg = H.to_long(rf.rows.assign(site=hf.site, date=hf.date, shift=hf.shift))
            vol = lg.groupby("material_group")["volume"].sum()
            st.session_state["hi_goto"] = (hf.site, hf.date, hf.shift)
            st.session_state["hi_ver"] = st.session_state.get("hi_ver", 0) + 1   # empty the uploader
            st.session_state["hi_msg"] = (
                f"{hf.site} {hf.date:%d %b %Y} {hf.shift} saved from {f.name}: {len(rf.rows)} lines, "
                f"{lg['rit'].sum():,.0f} trips, OB {vol.get('OB', 0):,.0f} BCM, coal {vol.get('CG', 0):,.0f} t. "
                "It is shown below; on the TV and in Dashboard → Hourly production pick this date and shift.")
            st.rerun()
