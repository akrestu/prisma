"""Unit Population: versioned master list of units and their site (Unit Population workbook, effective date)."""
import pandas as pd
import streamlit as st

from core import population as pop
from core.config import UNMAPPED, today_wib
from core.ingest import audit
from core.io import sha256
from core.ui import fmt_num, require, sites_for
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
cur_label = current.attrs.get("source", "") if current is not None else ""

k = st.columns(4)
k[0].metric("Versions", fmt_num(len(versions)))
k[1].metric("Units now", fmt_num(len(current)) if current is not None else "—")
k[2].metric("Without a site", fmt_num((current["site"] == UNMAPPED).sum()) if current is not None else "—")
k[3].metric("Sites", fmt_num(current.loc[current["site"] != UNMAPPED, "site"].nunique()) if current is not None
            else "—")
if cur_label:
    st.caption(f"In force today: {cur_label}.")

t_imp, t_now, t_hist = st.tabs(["Import", "Current units", "Versions"])

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
        view = current
        if q:
            view = current[current.astype(str).apply(lambda col: col.str.lower().str.contains(q, regex=False))
                           .any(axis=1)]
        st.dataframe(view, hide_index=True, width="stretch", height=480)
        # template layout, so the file can be edited and imported back as the next version
        st.download_button("Download as template (.xlsx)", lambda: pop.build_template(sites, current, today_wib()),
                           file_name=pop.file_name(today_wib()), on_click="ignore", key="pop_dl_cur",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

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
