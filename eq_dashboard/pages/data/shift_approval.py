"""Hourly Production approval for the Site Manager: submitted shifts (approve / reject) and change requests to
locked shifts (apply / reject). Every decision re-checks on the server that the user may review the site."""
import pandas as pd
import streamlit as st

from auth.access import can_review
from core import hourly as H
from core import shift_flow as SF
from core.config import WIB
from core.ingest import audit
from core.ui import fmt_num, refresh, require, sites_for
from db import repo
from db.engine import session_scope

user = require("shift_approval")
sites = sites_for(user)
st.title("Approve hourly shifts")
st.caption("Hourly Production shifts become official once you approve them. A change to an approved or closed "
           "shift (closing: 09:00 WIB the day after) arrives here as a change request.")

msg = st.session_state.pop("sa_msg", None)
if msg:
    st.success(msg)
mine = [x for x in sites if can_review(user, x, sites)]
with session_scope() as s:
    waiting = repo.shifts_waiting(s, mine) if mine else pd.DataFrame()
    changes = repo.change_requests(s, mine) if mine else pd.DataFrame()


def _totals(rows: pd.DataFrame, site, date, shift) -> dict:
    if rows.empty:
        return {"OB": 0.0, "CG": 0.0, "trips": 0.0, "lines": 0}
    lg = H.to_long(rows.assign(site=site, date=date, shift=shift,
                               muatan=pd.to_numeric(rows["muatan"], errors="coerce"),
                               **{c: pd.to_numeric(rows[c], errors="coerce") for c in H.R}))
    v = lg.groupby("material_group")["volume"].sum()
    return {"OB": v.get("OB", 0.0), "CG": v.get("CG", 0.0), "trips": lg["rit"].sum(), "lines": len(rows)}


def _metrics(t: dict, before: dict | None = None) -> None:
    c = st.columns(4)
    for col, (label, key, nd) in zip(c, [("OB (BCM)", "OB", 0), ("Coal (t)", "CG", 1), ("Trips", "trips", 0),
                                         ("Lines", "lines", 0)], strict=True):
        delta = None if before is None else t[key] - before[key]
        col.metric(label, fmt_num(t[key], nd), None if not delta else f"{delta:+,.{nd}f}")


def _lines(rows: pd.DataFrame, shift: str) -> pd.DataFrame:
    cols = ["loader", "operator", "hauler", "hauler_operator", "material", "disposal", "pit", "distance_m", *H.R]
    return rows.reindex(columns=cols).rename(columns={"disposal": "destination", "distance_m": "dist_h",
                                                      **dict(zip(H.R, H.SLOTS[shift], strict=True))})


def _check(site: str) -> None:
    """The queue filter alone is not an access check."""
    if not can_review(user, site, sites):
        raise ValueError(f"You may not review {site}.")


t_sh, t_cr = st.tabs([f"Submitted shifts ({len(waiting)})", f"Change requests ({len(changes)})"])

with t_sh:
    if waiting.empty:
        st.success("No shift is waiting for approval.")
    for r in waiting.itertuples():
        with st.container(border=True):
            with session_scope() as s:
                _, rows = repo.hourly_shift(s, r.site, r.date, r.shift)
            closed = " · closed" if SF.state(SF.SUBMITTED, r.date, SF.now()).closed else ""
            st.markdown(f"**{r.site} · {r.date:%a %d %b %Y} · {r.shift}**{closed} · submitted by {r.submitted_by} "
                        f"{r.submitted_at.astimezone(WIB):%d %b %H:%M} WIB"
                        + (f" · shift boss {r.coordinator}" if r.coordinator else ""))
            _metrics(_totals(rows, r.site, r.date, r.shift))
            with st.expander(f"{len(rows)} lines"):
                st.dataframe(_lines(rows, r.shift), hide_index=True, width="stretch")
            note = st.text_input("Comment (required when rejecting)", key=f"sa_note_{r.id}")
            a, _, b = st.columns([1, 4, 1])
            approve = a.button("Approve", type="primary", key=f"sa_ok_{r.id}")
            reject = b.button("Reject", key=f"sa_no_{r.id}")
            if approve or reject:
                try:
                    with session_scope() as s:
                        _check(r.site)
                        repo.review_shift(s, r.id, approve, user.username, note)
                        audit(s, user.username, "hourly_approve" if approve else "hourly_reject", r.site,
                              f"{r.date:%Y-%m-%d} {r.shift}" + (f" — {note.strip()}" if note.strip() else ""))
                except ValueError as e:
                    st.error(str(e))
                else:
                    refresh("hourly")
                    st.session_state["sa_msg"] = (f"{r.site} {r.date:%d %b} {r.shift} "
                                                  + ("approved." if approve else "sent back to the data officer."))
                    st.rerun()

with t_cr:
    if changes.empty:
        st.success("No change request is waiting.")
    for r in changes.itertuples():
        with st.container(border=True):
            with session_scope() as s:
                _, now_rows = repo.hourly_shift(s, r.site, r.date, r.shift)
                new_rows = repo.change_rows(s, r.id)
            st.markdown(f"**{r.site} · {r.date:%a %d %b %Y} · {r.shift}** "
                        f"({SF.LABEL.get(r.shift_status, r.shift_status)}) · requested by {r.requested_by} "
                        f"{r.requested_at.astimezone(WIB):%d %b %H:%M} WIB")
            st.markdown(f"Reason: {r.reason}")
            before = _totals(now_rows, r.site, r.date, r.shift)
            st.caption("After the change (difference to the current lines):")
            _metrics(_totals(new_rows, r.site, r.date, r.shift), before)
            c1, c2 = st.columns(2)
            with c1.expander("Current lines"):
                st.dataframe(_lines(now_rows, r.shift), hide_index=True, width="stretch")
            with c2.expander("Lines after the change", expanded=True):
                st.dataframe(_lines(new_rows, r.shift), hide_index=True, width="stretch")
            note = st.text_input("Comment (required when rejecting)", key=f"cr_note_{r.id}")
            a, _, b = st.columns([1.3, 4, 1])
            apply = a.button("Approve change", type="primary", key=f"cr_ok_{r.id}")
            reject = b.button("Reject", key=f"cr_no_{r.id}")
            if apply or reject:
                try:
                    with session_scope() as s:
                        _check(r.site)
                        repo.decide_change(s, r.id, apply, user.username, note)
                        audit(s, user.username, "hourly_change_approve" if apply else "hourly_change_reject", r.site,
                              f"{r.date:%Y-%m-%d} {r.shift} request #{r.id}"
                              + (f" — {note.strip()}" if note.strip() else ""))
                except ValueError as e:
                    st.error(str(e))
                else:
                    refresh("hourly")
                    st.session_state["sa_msg"] = (f"Change to {r.site} {r.date:%d %b} {r.shift} "
                                                  + ("applied." if apply else "rejected."))
                    st.rerun()
