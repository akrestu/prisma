"""Hourly Production input: trips per excavator × hauler per hour for one site and shift (web grid or Excel template).

Flash data: saved immediately without approval and shown on the hourly production TV screen within a minute.
"""
import logging

import pandas as pd
import streamlit as st

from core import hourly as H
from core import locations as LC
from core import shift_flow as SF
from core.config import UNMAPPED, WIB, now_wib
from core.ingest import audit
from core.ui import fmt_num, refresh, require, sites_for
from core.validate import StructureError
from db import repo
from db.engine import session_scope

user = require("hourly_input")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title("Input hourly production")
st.caption("Trips per hauler per production hour, entered here in the grid or uploaded with the Excel template of "
           "the shift. Saved lines show on the hourly TV within a minute; submit the shift for the Site Manager's "
           "approval before closing (09:00 WIB the next day).")
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
    remarks = repo.hourly_remarks(s, site, date, shift)
    prev = repo.previous_lines(s, site, date, shift) if sh is None else None
    units = repo.population_for(s, date)
    ops = repo.operators(s, site)
    mtg, hmt = repo.model_targets(s), repo.hourly_model_targets(s, site)
    locs = repo.haul_locations(s, site)
    coord_now = sh.coordinator if sh else ""
    stamp = f"{sh.updated_by} · {sh.updated_at.astimezone(WIB):%d %b %H:%M} WIB" if sh else ""
    cr = repo.pending_change(s, sh.id) if sh else None
    cr_info = (cr.requested_by, cr.requested_at, cr.reason) if cr else None
    flow = SF.state(sh.status if sh else None, date, SF.now(), cr is not None)
    review = (sh.reviewed_by, sh.reviewed_at, sh.review_note) if sh and sh.reviewed_by else None
if lf.empty:
    st.warning(f"No load factors for {site} yet. An Admin or Site Manager sets them in **Setup → Load factors**.")
    st.stop()

site_units = units[units["site"] == site] if units is not None else pd.DataFrame(columns=["unit_id", "type"])
is_type = lambda word: site_units["type"].fillna("").str.contains(word, case=False)  # noqa: E731
loaders = sorted(set(tg["unit_id"]) | set(site_units.loc[is_type("Load"), "unit_id"]))
haulers = sorted(site_units.loc[H.is_hauler(site_units), "unit_id"]) if len(site_units) else []
op_label = {n: f"{n} - {nm}" for n, nm in zip(ops["nrp"], ops["name"], strict=True)}
code_label = {k: f"{k} - {v}" for k, v in H.REMARKS.items()}
slots = H.SLOTS[shift]
GRID = ["loader", "loader_nrp", "material", "hauler", "hauler_model", "hauler_nrp", "pit", "disposal", "distance_m",
        "dist_v", *H.R]
pit_names, disp_names = LC.names(locs, "PIT"), LC.names(locs, "DISPOSAL")
unit_model = dict(zip(site_units["unit_id"], site_units["model"], strict=True)) if len(site_units) else {}


def to_grid(df: pd.DataFrame) -> pd.DataFrame:
    g = df.reindex(columns=GRID).copy()
    for c in ("loader_nrp", "hauler_nrp"):
        g[c] = g[c].map(lambda x: op_label.get(str(x), x) if pd.notna(x) else None)
    if "operator" in df:                                   # old lines carry a name instead of an NRP
        g["loader_nrp"] = g["loader_nrp"].fillna(df["operator"])
    g["hauler_model"] = g["hauler"].map(unit_model).fillna(g["hauler_model"])
    return g


def apply_edits(g: pd.DataFrame, edits: dict) -> pd.DataFrame:
    """The grid as the data editor shows it: `g` with the editor's edited / added / deleted rows applied."""
    g = g.copy()
    for i, change in (edits.get("edited_rows") or {}).items():
        for c, v in change.items():
            g.loc[int(i), c] = v
    g = g.drop(index=[int(i) for i in edits.get("deleted_rows") or []], errors="ignore")
    added = [r for r in edits.get("added_rows") or [] if r]
    if added:
        g = pd.concat([g, pd.DataFrame(added).reindex(columns=g.columns)], ignore_index=True)
    return g.reset_index(drop=True)


def fill_model(gkey: str, wkey: str) -> None:
    """Hauler ID picked or changed: put its model from the unit population in the grid straight away. The editor is
    rebuilt (new key) on the edited rows, so the change shows before saving."""
    edits = st.session_state.get(gkey) or {}
    touched = any("hauler" in ch for ch in (edits.get("edited_rows") or {}).values())         or any(r.get("hauler") for r in edits.get("added_rows") or [])
    if not touched:
        return
    g = apply_edits(st.session_state[wkey], edits)
    g["hauler_model"] = g["hauler"].map(unit_model).where(g["hauler"].notna(), g["hauler_model"])  # old model lines kept
    st.session_state[wkey] = g
    st.session_state[f"{wkey}_n"] = st.session_state.get(f"{wkey}_n", 0) + 1


def from_grid(g: pd.DataFrame) -> pd.DataFrame:
    return g.assign(remark_code=None, remark=None)     # remarks are entered per hour in their own table


# ------------------------------------------------------------------ approval status of the shift
with st.container(border=True):
    a, b = st.columns([4, 1.3], vertical_alignment="center")
    icon = {SF.APPROVED: ":material/verified:", SF.SUBMITTED: ":material/hourglass_top:",
            SF.REJECTED: ":material/undo:"}.get(flow.status, ":material/edit_note:")
    a.markdown(f"{icon} **{flow.label if sh else 'Not entered yet'}** · closing "
               f"{SF.closes_at(date).astimezone(WIB):%d %b %H:%M} WIB")
    if review and flow.status in (SF.APPROVED, SF.REJECTED):
        a.caption(f"{'Approved' if flow.status == SF.APPROVED else 'Rejected'} by {review[0]} · "
                  f"{review[1].astimezone(WIB):%d %b %H:%M} WIB" + (f" — {review[2]}" if review[2] else ""))
    if cr_info:
        a.caption(f"Change request by {cr_info[0]} ({cr_info[1].astimezone(WIB):%d %b %H:%M}) waiting for the Site "
                  f"Manager — {cr_info[2]}")
    if flow.locked:
        a.caption("Locked: edit the grid below and send a **change request**; the Site Manager approves it.")
    if flow.can_submit and b.button("Submit for approval", type="primary", key="hi_submit", width="stretch",
                                    icon=":material/send:"):
        try:
            with session_scope() as s:
                repo.submit_shift(s, site, date, shift, user.username)
                audit(s, user.username, "hourly_submit", site, f"{date:%Y-%m-%d} {shift}")
        except ValueError as e:
            st.error(str(e))
        else:
            refresh("hourly")
            st.session_state["hi_msg"] = f"{site} {date:%d %b} {shift} submitted to the Site Manager."
            st.rerun()

t_web, t_xls = st.tabs(["Web input", "Excel template"])

# ------------------------------------------------------------------ remarks per hour
@st.fragment
def remark_box() -> None:
    """Quick remarks: hour (now by default), excavator, code, note → saved at once, apart from the trip grid (its
    unsaved edits are kept: the grid holds them in the session)."""
    with session_scope() as s:
        rm = repo.hourly_remarks(s, site, date, shift)
    fleet = sorted(set(rows["loader"].dropna())) if len(rows) else []
    fleet = fleet or (sorted(set(prev["loader"].dropna())) if prev is not None and len(prev) else []) or loaders
    live = (date, shift) == (p_date, p_shift)
    with st.container(border=True):
        st.markdown("**Remarks per hour** · only when something happened (rain, breakdown, waiting…). "
                    "Saved at once and shown in that hour on the TV.")
        if flow.locked:
            st.caption("The shift is locked: remarks can no longer be added or deleted.")
        with st.form(f"hi_rm_{site}_{date}_{shift}", clear_on_submit=True, border=False):
            c = st.columns([1, 1.2, 2.2, 2.6, 0.9], vertical_alignment="bottom")
            hour = c[0].selectbox("Hour", slots, index=(p_slot - 1) if live else 0)
            last = st.session_state.get("hi_rm_loader")
            loader = c[1].selectbox("Excavator", fleet, index=fleet.index(last) if last in fleet else 0)
            code = c[2].selectbox("Remark code", list(code_label.values()), index=None, placeholder="Pick a code")
            note = c[3].text_input("Note (optional)", placeholder="e.g. hujan deras, front basah")
            add = c[4].form_submit_button("Add", type="primary", width="stretch", icon=":material/add:",
                                          disabled=flow.locked)
            with st.expander("More: several hours, one truck"):
                d1, d2 = st.columns(2)
                until = d1.selectbox("Until hour", ["(same hour)", *slots], key=None)
                hauler = d2.selectbox("Hauler ID", haulers, index=None, placeholder="whole fleet")
        if add:
            if code is None and not note.strip():
                st.error("Pick a remark code or write a note.")
            else:
                a = slots.index(hour) + 1
                b = a if until == "(same hour)" else slots.index(until) + 1
                try:
                    with session_scope() as s:
                        n = repo.add_hourly_remark(s, site, date, shift, a, b, loader, (code or "")[:3] or None,
                                                   note, user.username, hauler)
                        audit(s, user.username, "hourly_remark", site,
                              f"{date:%Y-%m-%d} {shift} {H.span_label(shift, min(a, b), max(a, b))} {loader} "
                              f"{(code or '')[:3]} {note.strip()}".strip())
                except ValueError as e:
                    st.error(str(e))
                    return
                st.session_state["hi_rm_loader"] = loader
                refresh("hourly")
                st.toast(f"Remark added ({n} hour{'s' if n > 1 else ''}).")
                st.rerun()
        ev = H.group_remarks(rm)
        if ev.empty:
            st.caption("No remarks for this shift yet.")
        for r in ev.itertuples():
            a, b = st.columns([12, 1], vertical_alignment="center")
            note = f" — {r.remark}" if isinstance(r.remark, str) and r.remark else ""
            truck = f" · {r.hauler}" if isinstance(r.hauler, str) and r.hauler else ""
            a.markdown(f"`{H.span_label(shift, r.slot_from, r.slot_to)}` **{r.loader}**{truck} · "
                       f"{H.remark_label(r.code) or ''}{note}")
            if b.button("", key=f"hi_rm_del_{r.ids[0]}", icon=":material/delete:", help="Delete this remark",
                        disabled=flow.locked):
                try:
                    with session_scope() as s:
                        repo.delete_hourly_remarks(s, r.ids)
                        audit(s, user.username, "hourly_remark_delete", site,
                              f"{date:%Y-%m-%d} {shift} {H.span_label(shift, r.slot_from, r.slot_to)} {r.loader}")
                except ValueError as e:
                    st.error(str(e))
                    return
                refresh("hourly")
                st.rerun()


# ------------------------------------------------------------------ web grid
with t_web:
    remark_box()
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
        st.caption("⚠ No operators for this site yet: add them in **Setup → Operators** to pick them by NRP.")
    cfg = {
        "loader": st.column_config.SelectboxColumn("Excavator", options=loaders, required=True),
        "loader_nrp": st.column_config.SelectboxColumn("Operator", options=list(op_label.values()),
                                                       width="medium"),
        "material": st.column_config.SelectboxColumn("Material", options=sorted(lf["material"].unique()),
                                                     required=True),
        "hauler": st.column_config.SelectboxColumn("Hauler ID", options=haulers, required=True),
        "hauler_model": st.column_config.TextColumn("Hauler model", disabled=True,
                                                    help="Filled from the unit population when the Hauler ID is "
                                                         "picked; not typed"),
        "hauler_nrp": st.column_config.SelectboxColumn("Hauler operator", options=list(op_label.values()),
                                                       width="medium"),
        "pit": st.column_config.SelectboxColumn("PIT", options=pit_names, width="small",
                                                help="Loading pit (the site's list, of the line's material)"),
        "disposal": st.column_config.SelectboxColumn("Disposal", options=disp_names, width="medium",
                                                     help="Where the hauler unloads (the site's list, of the line's "
                                                          "material)"),
        "distance_m": st.column_config.NumberColumn("H distance (m)", format="%.0f",
                                                    help="Horizontal distance, typed by the engineering checker"),
        "dist_v": st.column_config.NumberColumn("V distance (m)", format="%.0f",
                                                help="Vertical distance, typed by the engineering checker"),
        **{r: st.column_config.NumberColumn(lbl, min_value=0, max_value=20, step=1, format="%d", width="small")
           for r, lbl in zip(H.R, slots, strict=True)},
    }
    wkey = f"hi_work_{site}_{date}_{shift}_{ver}"            # the rows the editor starts from (models filled in)
    if wkey not in st.session_state:
        st.session_state[wkey] = to_grid(base).reset_index(drop=True)
    work = st.session_state[wkey]
    gkey = f"hi_grid_{site}_{date}_{shift}_{ver}_{st.session_state.get(f'{wkey}_n', 0)}"
    grid = st.data_editor(work, num_rows="dynamic", hide_index=True, width="stretch", column_config=cfg,
                          key=gkey, height=min(600, 38 * (len(work) + 3) + 40), on_change=fill_model,
                          args=(gkey, wkey))
    res = H.resolve(from_grid(grid), lf, tg, units, ops, model_targets=mtg, hourly_models=hmt,
                    locations=locs)
    st.caption("One row per hauler and disposal. When a hauler goes to a second disposal, or its operator "
               "changes during the shift, add a second row for the same hauler.")
    if not pit_names or not disp_names:
        st.caption("⚠ No PIT or disposal for this site yet: an Admin or Site Manager adds them in "
                   "**Setup → PIT & disposals**.")

    edits = st.session_state.get(gkey) or {}
    dirty = any(edits.get(k) for k in ("edited_rows", "added_rows", "deleted_rows")) \
        or st.session_state.get(f"{wkey}_n", 0) > 0         or coord != coord_now or (sh is None and len(base) > 0)   # lines copied from the previous shift: not saved yet
    if dirty:
        st.warning("Unsaved changes. Changing the site, date or shift discards them: press **Save shift** first.")
    if res.problems:
        st.error(f"{len(res.problems)} problem(s) to fix before saving:\n\n"
                 + "\n".join(f"- {p}" for p in res.problems))
    for w in res.warnings:
        st.warning(w)
    if len(res.rows) and not res.problems:
        long = H.to_long(res.rows.assign(site=site, date=date, shift=shift))
        tot = long.groupby("material_group")["volume"].sum()
        k = st.columns(5)
        k[0].metric("OB (BCM)", fmt_num(tot.get("OB", 0)))
        k[1].metric("Coal (t)", fmt_num(tot.get("CG", 0), 1))
        k[2].metric("Trips", fmt_num(long["rit"].sum()))
        k[3].metric("Fleets", res.rows["loader"].nunique())
        k[4].metric("Haulers", res.rows["hauler"].nunique())
    if flow.locked:
        reason = st.text_input("Reason for the change (required)", key=f"hi_cr_reason_{site}_{date}_{shift}",
                               placeholder="e.g. ritase WDT017 jam 09-10 salah ketik, hasil cek form")
        if st.button("Send change request", type="primary", key="hi_cr", disabled=bool(res.problems),
                     icon=":material/send:") and not res.problems:
            try:
                with st.spinner("Sending…"), session_scope() as s:
                    repo.request_change(s, site, date, shift, coord, res.rows, reason, user.username)
                    audit(s, user.username, "hourly_change_request", site,
                          f"{date:%Y-%m-%d} {shift}: {len(res.rows)} lines — {reason.strip()}")
            except ValueError as e:
                st.error(str(e))
            else:
                refresh("hourly")
                st.session_state["hi_ver"] = ver + 1
                st.session_state["hi_msg"] = (f"Change request for {site} {date:%d %b} {shift} sent to the Site "
                                              "Manager; the shift keeps its current lines until it is approved.")
                st.rerun()
    elif st.button("Save shift", type="primary", key="hi_save", disabled=bool(res.problems)) and not res.problems:
        try:
            with st.spinner("Saving the shift…"), session_scope() as s:
                repo.save_hourly(s, site, date, shift, coord, res.rows, user.username, "web")
                audit(s, user.username, "hourly_save", site, f"{date:%Y-%m-%d} {shift}: {len(res.rows)} lines")
        except ValueError as e:                            # locked meanwhile (approved, or closing passed)
            st.error(str(e))
        else:
            refresh("hourly")
            st.session_state["hi_ver"] = ver + 1
            again = " Submit it again for approval." if flow.status in (SF.SUBMITTED, SF.REJECTED) else ""
            st.session_state["hi_msg"] = f"{site} {date:%d %b} {shift} saved ({len(res.rows)} lines).{again}"
            st.rerun()

# ------------------------------------------------------------------ Excel template
with t_xls:
    st.markdown("For bulk entry or when the connection is poor: download the template for this site and shift, "
                "fill in the trips in Excel, then upload it here. Uploading **replaces** the shift.")
    lines = rows if sh is not None else (prev if prev is not None else None)
    st.download_button(f"Download template · {site} {date:%d %b} {shift}",
                       lambda: H.build_template(site, date, shift, lf, tg, lines, coord_now, units, ops,
                                                remarks if sh is not None else None, locs),
                       file_name=H.file_name(site, date, shift), on_click="ignore",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    f = st.file_uploader("Filled template (.xlsx)", type=["xlsx"], key=f"hi_file_{st.session_state.get('hi_ver', 0)}",
                         max_upload_size=10)
    if f is not None:
        try:
            with st.spinner(f"Reading {f.name}…"):
                hf = H.parse_template(f.getvalue())
        except StructureError as e:
            for p in e.problems:
                st.error(p)
            st.stop()
        except Exception as e:  # unreadable / corrupt file
            logging.getLogger(__name__).warning("workbook could not be opened", exc_info=True)
            st.error(f"The workbook could not be opened ({type(e).__name__}). Save it again in Excel as .xlsx and "
                     "retry.")
            st.stop()
        if hf.site not in sites:
            st.error(f"The file is for site {hf.site}, which you do not have access to.")
            st.stop()
        with session_scope() as s:
            lf_f, tg_f = repo.load_factors(s, hf.site), repo.loader_targets(s, hf.site)
            exists, _ = repo.hourly_shift(s, hf.site, hf.date, hf.shift)
            flow_f = SF.state(exists.status if exists else None, hf.date, SF.now())
            units_f = repo.population_for(s, hf.date)
            ops_f = repo.operators(s, hf.site)
            mtg_f = repo.model_targets(s)
            hmt_f = repo.hourly_model_targets(s, hf.site)
            locs_f = repo.haul_locations(s, hf.site)
        rf = H.resolve(hf.rows, lf_f, tg_f, units_f, ops_f, model_targets=mtg_f, hourly_models=hmt_f,
                       locations=locs_f)
        rm_f, rm_problems = H.clean_remarks(hf.remarks, hf.shift, sorted(set(rf.rows["loader"].dropna()))
                                            if len(rf.rows) else None)
        rf.problems.extend(rm_problems)
        st.markdown(f"**{hf.site} · {hf.date:%d %b %Y} · {hf.shift}** · {len(rf.rows)} lines"
                    + (f" · {len(rm_f)} remark(s)" if len(rm_f) else "")
                    + (f" · coordinator {hf.coordinator}" if hf.coordinator else ""))
        for p in rf.problems:
            st.error(p)
        for w in rf.warnings:
            st.warning(w)
        ok = True
        if flow_f.locked:
            st.warning(f"This shift is locked ({flow_f.label}): the file is sent as a change request for the Site "
                       "Manager (remarks in the file are not changed).")
            why = st.text_input("Reason for the change (required)", key=f"hi_xcr_{st.session_state.get('hi_ver', 0)}")
            if not rf.problems and st.button("Send change request", type="primary", key="hi_xcr_send"):
                try:
                    with session_scope() as s:
                        repo.request_change(s, hf.site, hf.date, hf.shift, hf.coordinator, rf.rows, why,
                                            user.username)
                        audit(s, user.username, "hourly_change_request", hf.site,
                              f"{hf.date:%Y-%m-%d} {hf.shift}: {len(rf.rows)} lines from {f.name} — {why.strip()}")
                except ValueError as e:
                    st.error(str(e))
                    st.stop()
                refresh("hourly")
                st.session_state["hi_goto"] = (hf.site, hf.date, hf.shift)
                st.session_state["hi_ver"] = st.session_state.get("hi_ver", 0) + 1
                st.session_state["hi_msg"] = f"Change request for {hf.site} {hf.date:%d %b} {hf.shift} sent."
                st.rerun()
            st.stop()
        if exists is not None:
            st.warning("This shift already has data; saving replaces it.")
            ok = st.checkbox("Replace the existing lines of this shift", key=f"hi_xrep_{st.session_state.get('hi_ver', 0)}")
        if not rf.problems and st.button("Save uploaded shift", type="primary", key="hi_xsave", disabled=not ok):
            try:
                with st.spinner("Saving the shift…"), session_scope() as s:
                    repo.save_hourly(s, hf.site, hf.date, hf.shift, hf.coordinator, rf.rows, user.username, "excel",
                                     remarks=rm_f)
                    audit(s, user.username, "hourly_upload", hf.site,
                          f"{hf.date:%Y-%m-%d} {hf.shift}: {len(rf.rows)} lines from {f.name}")
            except ValueError as e:
                st.error(str(e))
                st.stop()
            refresh("hourly")
            lg = H.to_long(rf.rows.assign(site=hf.site, date=hf.date, shift=hf.shift))
            vol = lg.groupby("material_group")["volume"].sum()
            st.session_state["hi_goto"] = (hf.site, hf.date, hf.shift)
            st.session_state["hi_ver"] = st.session_state.get("hi_ver", 0) + 1   # empty the uploader
            st.session_state["hi_msg"] = (
                f"{hf.site} {hf.date:%d %b %Y} {hf.shift} saved from {f.name}: {len(rf.rows)} lines, "
                f"{lg['rit'].sum():,.0f} trips, OB {vol.get('OB', 0):,.0f} BCM, coal {vol.get('CG', 0):,.0f} t. "
                "It is shown below; on the TV and in Production → Hourly production pick this date and shift.")
            st.rerun()
