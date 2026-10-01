"""Admin only: delete Unit Population, Production Data and/or Hourly Production, optionally for some sites and a
period. A preview counts what will go; the typed phrase confirms. Settings, users and targets are never touched."""
import datetime as dt

import streamlit as st

from core import filters as F
from core.config import UNMAPPED, today_wib
from core.ingest import audit
from core.ui import fmt_num, refresh, require, sites_for
from core.validate import HOURLY_PRODUCTION, PRODUCTION_DATA, UNIT_POPULATION
from db import repo
from db.engine import session_scope

PHRASE = "DELETE"
ALL_TIME, RANGE = "All time", "Date range"

user = require("delete_data")
st.title("Delete data")
st.caption("Remove imported data per dataset, for all or some sites and a period. Users, sites, targets, plans, "
           "load factors, operators, TV devices and the audit log are always kept.")

done = st.session_state.pop("delete_done", None)
if done:
    st.success(done)

sites = [x for x in sites_for(user) if x != UNMAPPED]
datasets = st.pills("Datasets", [UNIT_POPULATION, PRODUCTION_DATA, HOURLY_PRODUCTION], selection_mode="multi",
                    key="del_sets", help="Pick one or more")
if not datasets:
    st.info("Pick the dataset(s) to delete.")
    st.stop()

a, b = st.columns([1, 1])
site_based = PRODUCTION_DATA in datasets or HOURLY_PRODUCTION in datasets
picked_sites = None
if site_based:
    every = a.toggle("All sites", value=True, key="del_all_sites",
                     help="Off: choose sites. Unit Population is one list for all sites, so it ignores this.")
    if not every:
        picked_sites = a.multiselect("Sites", sites, key="del_sites")
        if not picked_sites:
            st.info("Choose at least one site.")
            st.stop()
when = b.segmented_control("Period", [ALL_TIME, RANGE], default=ALL_TIME, key="del_when") or ALL_TIME
d0 = d1 = None
if when == RANGE:
    today = today_wib()
    rng = b.date_input("From – to", (today.replace(day=1), today), key="del_range",
                       help="Production Data counts whole months: a month is deleted when its first day is in the "
                            "range. Hourly Production uses the shift date, Unit Population the effective date.")
    if not (isinstance(rng, (list, tuple)) and len(rng) == 2):
        st.info("Pick both dates of the range.")
        st.stop()
    d0, d1 = rng


def scope(dry_run: bool, s) -> dict[str, dict[str, int]]:
    out = {}
    if UNIT_POPULATION in datasets:
        out[UNIT_POPULATION] = repo.delete_population(s, d0, d1, dry_run=dry_run)
    if PRODUCTION_DATA in datasets:
        # whole months only: the first month that starts on or after d0
        m0 = None if d0 is None else d0 if d0.day == 1 else F.month_end(d0) + dt.timedelta(days=1)
        out[PRODUCTION_DATA] = repo.delete_production(s, picked_sites, m0, d1, dry_run=dry_run)
    if HOURLY_PRODUCTION in datasets:
        out[HOURLY_PRODUCTION] = repo.delete_hourly(s, picked_sites, d0, d1, dry_run=dry_run)
    return out


with st.spinner("Counting what would be deleted…"), session_scope() as s:
    preview = scope(True, s)

st.subheader("What will be deleted")
LABELS = {"versions": "versions", "units": "units", "months": "site × months", "fact_event": "event rows",
          "fact_ritase_jam": "trip rows", "fact_coal_tiket": "coal tickets", "fact_fuel": "fuel rows",
          "shifts": "shifts", "lines": "hourly lines"}
cols = st.columns(len(preview))
total = 0
for col, (name, c) in zip(cols, preview.items(), strict=True):
    with col.container(border=True):
        st.markdown(f"**{name}**")
        shown = [k for k in LABELS if k in c and not (name == PRODUCTION_DATA and k == "versions")]
        for k in shown:
            st.markdown(f"{fmt_num(c[k])} {LABELS[k]}")
        total += c.get("versions", 0) + c.get("shifts", 0)
where = "all sites" if picked_sites is None else ", ".join(picked_sites)
period = "all time" if when == ALL_TIME else f"{d0:%d %b %Y} – {d1:%d %b %Y}"
st.caption(f"Scope: {where} · {period}.")
if PRODUCTION_DATA in datasets:
    st.caption("Production Data: every version of the chosen site-months goes (PUBLISHED, PENDING, REJECTED, "
               "SUPERSEDED); dashboards and TVs show nothing for them until a new file is imported and approved.")
if UNIT_POPULATION in datasets:
    st.caption("Unit Population: Production Data already imported keeps the units it was imported with; new "
               "imports need a population version again.")

if total == 0:
    st.info("Nothing matches this selection.")
    st.stop()

st.warning("This cannot be undone. Keep the original Excel files before deleting.")
with st.form("delete_form"):
    typed = st.text_input(f"Type **{PHRASE}** to confirm")
    go = st.form_submit_button("Delete", type="primary")
if go:
    if typed.strip() != PHRASE:
        st.error(f"Type {PHRASE} exactly to confirm.")
    else:
        with st.spinner("Deleting…"), session_scope() as s:
            result = scope(False, s)
            for name, c in result.items():
                detail = ", ".join(f"{k} {v:,}" for k, v in c.items() if v)
                audit(s, user.username, "delete_data", None, f"{name} · {where} · {period}: {detail or 'nothing'}")
        refresh("all")
        st.session_state["delete_done"] = "Deleted: " + " · ".join(
            f"{name} ({', '.join(f'{fmt_num(v)} {LABELS.get(k, k)}' for k, v in c.items() if v and k in LABELS)})"
            for name, c in result.items())
        st.rerun()
