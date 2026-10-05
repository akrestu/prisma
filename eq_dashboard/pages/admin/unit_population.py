"""Unit Population: versioned master list of units and their site (Unit Population workbook, effective date)."""
import logging

import pandas as pd
import streamlit as st

from core import population as pop
from core.config import UNMAPPED, today_wib
from core.ingest import audit
from core.io import sha256
from core.ui import excel_download, fmt_num, require, sites_for
from core.validate import StructureError, file_stem
from db import repo
from db.engine import session_scope

MAX_MB = 20

user = require("unit_population")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title(pop.DATASET)
st.caption("The master list of units and the site that owns each one. It changes rarely: upload a new version only "
           "when a unit arrives, leaves, moves site or changes type/model. Each version applies from its effective "
           "date, so older months keep the population that was valid then.")

msg = st.session_state.pop("pop_msg", None)
if msg:
    st.success(msg)

with session_scope() as s:
    versions = repo.population_versions(s)
    current = repo.population_for(s, today_wib())
    all_units = repo.population_all_units(s) if len(versions) > 1 else pd.DataFrame()
moves = pop.movements(all_units, versions)
cur_label = current.attrs.get("source", "") if current is not None else ""

k = st.columns(4)
k[0].metric("Versions", fmt_num(len(versions)))
k[1].metric("Units now", fmt_num(len(current)) if current is not None else "—")
k[2].metric("Without a site", fmt_num((current["site"] == UNMAPPED).sum()) if current is not None else "—")
k[3].metric("Sites", fmt_num(current.loc[current["site"] != UNMAPPED, "site"].nunique()) if current is not None
            else "—")
if cur_label:
    st.caption(f"In force today: {cur_label}.")

n_moved = int((moves["change"] == "moved").sum())
t_imp, t_now, t_move, t_hist = st.tabs(["Import", "Current units",
                                        f"Unit movements ({n_moved})" if n_moved else "Unit movements", "Versions"])

# ------------------------------------------------------------------ import
with t_imp:
    c1, c2 = st.columns([2, 1])
    f = c1.file_uploader(f"Choose a {pop.DATASET} workbook (.xlsx or .xlsb)", type=["xlsx", "xlsb"],
                         key=f"pop_file_{st.session_state.get('pop_ver', 0)}", max_upload_size=MAX_MB)
    with c2:
        st.download_button("Download template (.xlsx)",
                           lambda: pop.build_template(sites, current, today_wib()),
                           file_name=pop.file_name(today_wib()), on_click="ignore",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.caption("Pre-filled with the units in force today: change only what changed and upload it back.")
    if f is not None:
        data = f.getvalue()
        try:
            with st.spinner(f"Reading {f.name}…"):
                pf = pop.parse_population(data)
        except StructureError as e:
            for p_ in e.problems:
                st.error(p_)
            st.stop()
        except Exception as e:  # unreadable file
            logging.getLogger(__name__).warning("workbook could not be opened", exc_info=True)
            st.error(f"The workbook could not be opened ({type(e).__name__}). Save it again as .xlsx and retry.")
            st.stop()

        default_eff = pop.effective_from_name(f.name) or pop.meta_effective(data) or today_wib().replace(day=1)
        a, b = st.columns([1, 2])
        eff = a.date_input("Effective from", default_eff, key="pop_eff",
                           help="This version applies from this date until the next version's date.")
        note = b.text_input("Note (optional)", key="pop_note", placeholder="e.g. 3 new 777E arrived, WEX015 to BAU")

        with session_scope() as s:
            before = repo.population_for(s, eff)
        if not user.is_admin:
            # the population covers every site: a Data Officer changes only the units of their own sites
            pf.units, ignored = pop.restrict(before, pf.units, sites)
            if len(ignored):
                st.warning(f"{len(ignored)} change(s) outside your sites ({', '.join(sites)}) are not applied; "
                           "those units stay as in the version in force. Ask an Admin to change them.")
                with st.expander("Show the changes that are not applied"):
                    st.dataframe(ignored, hide_index=True, width="stretch")
        changes = pop.diff(before, pf.units)
        counts = changes["change"].str.split(" ").str[0].value_counts()
        st.subheader(f"Check · {len(pf.units):,} units")
        c = st.columns(4)
        c[0].metric("Added", int(counts.get("added", 0)))
        c[1].metric("Removed", int(counts.get("removed", 0)))
        c[2].metric("Moved site", int(counts.get("moved", 0)))
        c[3].metric("Type / model changed", int(counts.get("type/model", 0)))
        by_site = pf.units.groupby("site").size().rename("units").reset_index()
        st.dataframe(by_site, hide_index=True, width="content")
        if pf.duplicates:
            st.warning(f"Listed more than once (first row kept): {', '.join(pf.duplicates[:20])}")
        if pf.without_site:
            st.warning(f"{len(pf.without_site)} unit(s) without a site stay UNMAPPED: "
                       f"{', '.join(pf.without_site[:20])}")
        if len(changes):
            with st.expander(f"Show {len(changes)} change(s) against the version in force on {eff:%d %b %Y}",
                             expanded=len(changes) <= 30):
                st.dataframe(changes, hide_index=True, width="stretch")
        elif before is not None:
            st.info("No differences with the version in force on that date.")
        same_day = versions[versions["effective_from"] == eff] if len(versions) else versions
        if len(same_day):
            st.caption(f"A version effective {eff:%d %b %Y} already exists (#{int(same_day['id'].iloc[0])}); "
                       "the new one takes precedence because it is newer.")
        if len(changes) == 0 and before is not None:
            st.caption("Saving is possible but not needed: the population would stay the same.")
        if st.button("Save version", type="primary", key="pop_save"):
            with st.spinner(f"Saving {len(pf.units):,} units…"), session_scope() as s:
                v = repo.save_population(s, pf.units, eff, f.name, sha256(data), user.id, note)
                audit(s, user.username, "population_import", None,
                      f"#{v.id} effective {eff:%Y-%m-%d}: {len(pf.units)} units, {len(changes)} changes")
                vid = v.id
            st.session_state["pop_ver"] = st.session_state.get("pop_ver", 0) + 1   # empty the uploader
            st.session_state["pop_msg"] = (f"Version #{vid} saved: {len(pf.units):,} units effective "
                                           f"{eff:%d %b %Y}. It applies to Production Data imports from that month "
                                           "on.")
            st.rerun()
    st.caption("Saving a version does not change data already imported. To apply it to a month that is already "
               "published, import that month's Production Data again.")

# ------------------------------------------------------------------ current units
with t_now:
    if current is None:
        st.info(f"No population version yet. Import a {pop.DATASET} workbook first.")
    else:
        q = st.text_input("Search", key="pop_q", placeholder="unit, type, model, site…").strip().lower()
        if len(versions) and "Population version" in cur_label:
            first = pd.Timestamp(versions["effective_from"].min()).date()
            current = current.assign(site_since=pop.site_since(moves, current, first))
        view = current
        if q:
            view = current[current.astype(str).apply(lambda col: col.str.lower().str.contains(q, regex=False))
                           .any(axis=1)]
        st.dataframe(view, hide_index=True, width="stretch", height=480)
        # template layout, so the file can be edited and imported back as the next version
        st.download_button("Download as template (.xlsx)", lambda: pop.build_template(sites, current, today_wib()),
                           file_name=pop.file_name(today_wib()), on_click="ignore", key="pop_dl_cur",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ------------------------------------------------------------------ movements
with t_move:
    st.caption("Built from the versions: a unit that is in a different site, new, or gone in the next version. "
               "The date is the effective date of the version that shows the change.")
    if len(versions) < 2:
        st.info("Movements appear once there are at least two versions (e.g. one per year, or one whenever units "
                "move).")
    elif moves.empty:
        st.info("No unit changed site, arrived or left between the versions.")
    else:
        f1, f2, f3 = st.columns([2, 2, 2])
        q = f1.text_input("Unit", key="mv_q", placeholder="e.g. WEX021").strip().upper()
        kinds = f2.multiselect("Change", ["moved", "arrived", "left"], default=["moved", "arrived", "left"],
                               key="mv_kind")
        dmin, dmax = pd.Timestamp(moves["date"].min()).date(), pd.Timestamp(moves["date"].max()).date()
        rng = f3.date_input("Effective between", (dmin, dmax), key="mv_rng", format="DD/MM/YYYY")
        view = moves[moves["change"].isin(kinds)]
        if q:
            view = view[view["unit_id"].str.upper().str.contains(q, regex=False)]
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            view = view[(view["date"] >= rng[0]) & (view["date"] <= rng[1])]
        c = view["change"].value_counts()
        m1, m2, m3 = st.columns(3)
        m1.metric("Moved site", int(c.get("moved", 0)))
        m2.metric("Arrived", int(c.get("arrived", 0)))
        m3.metric("Left", int(c.get("left", 0)))
        show = view.assign(route=[f"{a or '—'} → {b or '—'}" for a, b in zip(view["from_site"], view["to_site"],
                                                                           strict=True)])
        st.dataframe(show[["date", "unit_id", "change", "route", "type", "model", "version_id"]], hide_index=True,
                     width="stretch", height=420,
                     column_config={"date": st.column_config.DateColumn("Effective from", format="DD MMM YYYY"),
                                    "unit_id": "Unit", "change": "Change", "route": "Site", "type": "Type",
                                    "model": "Model", "version_id": "Version"})
        if q and len(view):
            st.caption(f"History of {q}: " + " · ".join(
                f"{r.date:%d %b %Y} {r.change} {r.route}" for r in show.sort_values("date").itertuples()))
        excel_download(show.drop(columns=["route"]), f"unit_movements_{today_wib():%Y-%m-%d}.xlsx", key="mv_dl")

# ------------------------------------------------------------------ versions
with t_hist:
    if versions.empty:
        st.info("No versions yet.")
    else:
        show = pd.DataFrame({
            "Version": versions["id"], "Effective from": pd.to_datetime(versions["effective_from"]).dt.strftime(
                "%d %b %Y"), "Units": versions["units"], "File": versions["filename"], "Note": versions["note"],
            "Uploaded": pd.to_datetime(versions["uploaded_at"]).dt.tz_convert("Asia/Jakarta").dt.strftime(
                "%d %b %Y %H:%M"), "By": versions["uploader"]})
        st.dataframe(show, hide_index=True, width="stretch")
        pick = st.selectbox("Download a version", versions["id"].tolist(), key="pop_pick",
                            format_func=lambda i: f"#{i} · effective "
                            f"{versions.loc[versions['id'] == i, 'effective_from'].iloc[0]:%d %b %Y}")
        with session_scope() as s:
            units_v = repo.population_units(s, int(pick))
        eff_v = pd.Timestamp(versions.loc[versions["id"] == pick, "effective_from"].iloc[0]).date()
        st.download_button(f"Download version #{pick} as template (.xlsx)",
                           lambda: pop.build_template(sites, units_v, eff_v),
                           file_name=f"{file_stem(pop.DATASET)}_{eff_v:%Y-%m-%d}_v{pick}.xlsx", on_click="ignore",
                           key="pop_dl_v", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
