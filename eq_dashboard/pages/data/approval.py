"""Approval queue per site: KPI preview + data quality → Approve / Reject."""
import streamlit as st

from auth.access import can_review
from core import dash, metrics
from core import ingest as ing
from core.ui import fmt_num, fmt_pct, require, sites_for
from db import models as m
from db import repo
from db.engine import session_scope


@st.cache_data(ttl=900, max_entries=30, show_spinner=False)
def _preview(upload_id: int, site: str):
    """KPIs + findings of one pending version; cached so typing a comment does not reload ~60,000 events.
    An upload's rows never change after import, so the cache cannot go stale."""
    with session_scope() as s:
        ev = repo.events(s, upload_id, site)
        stp = repo.stoppages(s, upload_id, site)
        findings = repo.dq_findings(s, upload_id, site)
    if ev.empty:
        return None, None, findings
    return metrics.kpis(ev), metrics.reliability(ev, stp), findings


@st.dialog("Confirm")
def _confirm(action: str, row, comment: str) -> None:
    """Publishing reaches every Viewer and TV at once, so both decisions are confirmed."""
    what = f"**{row['site']} · {row['month']:%B %Y}** (upload #{row['upload_id']})"
    if action == "approve":
        st.markdown(f"Publish {what}? Viewers and TVs will show it right away; the previous version for this "
                    "site & month becomes SUPERSEDED.")
    else:
        st.markdown(f"Reject {what}?  \nReason: {comment}")
    a, b = st.columns(2)
    if a.button("Approve and publish" if action == "approve" else "Reject upload", type="primary", width="stretch"):
        try:
            with session_scope() as s:
                us = s.get(m.UploadSite, int(row["id"]))
                if action == "approve":
                    ing.publish(s, us, user.id, user.username, comment=comment)
                else:
                    ing.reject(s, us, user.id, user.username, comment)
        except ValueError as e:
            st.error(str(e))
            return
        st.toast(f"{row['site']} {row['month']:%Y-%m} " + ("PUBLISHED" if action == "approve" else "rejected"))
        st.rerun()
    if b.button("Cancel", width="stretch"):
        st.rerun()


@st.dialog("Approve all")
def _approve_all(rows) -> None:
    """Bulk approval for a yearly import: every listed site × month without critical findings, oldest first."""
    st.markdown(f"Publish **{len(rows)}** site × month version(s) without critical findings? Viewers and TVs show "
                "them right away; the previous version of each site & month becomes SUPERSEDED.")
    st.caption(", ".join(f"{r['site']} {r['month']:%b %Y}" for r in rows))
    a, b = st.columns(2)
    if a.button("Approve and publish all", type="primary", width="stretch"):
        done, failed = 0, []
        bar = st.progress(0.0, text="Publishing…")
        for i, r in enumerate(rows, 1):
            try:
                with session_scope() as s:
                    ing.publish(s, s.get(m.UploadSite, int(r["id"])), user.id, user.username, comment="approve all")
                done += 1
            except ValueError as e:
                failed.append(str(e))
            bar.progress(i / len(rows), text=f"Published {i} of {len(rows)}")
        st.toast(f"{done} version(s) PUBLISHED" + (f", {len(failed)} skipped" if failed else ""))
        st.rerun()
    if b.button("Cancel", width="stretch", key="all_cancel"):
        st.rerun()


user = require("approval")
sites = sites_for(user)
st.title("Data approval")

with session_scope() as s:
    queue = repo.upload_sites(s, sites, [ing.PENDING])
queue = queue[[can_review(user, x, sites) for x in queue["site"]]] if len(queue) else queue

if queue.empty:
    st.success("Nothing is waiting for approval.")
    st.stop()

n_crit = sum(1 for d in queue["dq_summary"] if (d or {}).get("critical"))
dash.summary(f"{len(queue)} site upload(s) waiting for approval",
             f"{n_crit} with critical data quality findings" if n_crit else "none with critical data quality findings",
             f"oldest from {queue['uploaded_at'].min():%d %b %H:%M}")
st.caption("Data reaches Viewers and TVs only after approval; the previous version for the same site & month "
           "automatically becomes SUPERSEDED.")

# newest pending version per site × month, without critical findings (older duplicates and critical ones are
# reviewed one by one below)
clean_rows = (queue[[not (d or {}).get("critical") for d in queue["dq_summary"]]]
              .sort_values("upload_id").drop_duplicates(["site", "month"], keep="last").sort_values(["month", "site"]))
if len(clean_rows) > 1:
    a, b = st.columns([1.3, 4])
    if a.button(f"Approve all {len(clean_rows)} without critical findings", key="approve_all"):
        _approve_all(clean_rows.to_dict("records"))
    b.caption("Useful after a yearly import. Versions with critical findings stay in the list for a one-by-one "
              "review.")

for _, row in queue.iterrows():
    dq = row["dq_summary"] or {}
    summ = row["summary"] or {}
    head = (f"**{row['site']}** · {row['month']:%B %Y} · upload #{row['upload_id']} · {row['filename']} · "
            f"by {row['uploader'] or '-'}")
    with st.container(border=True):
        st.markdown(head)
        k, r, findings = _preview(int(row["upload_id"]), row["site"])
        c = st.columns(4)
        c[0].metric("Units", summ.get("units", 0))
        c[1].metric("PA", fmt_pct(k["PA"].iloc[0]) if k is not None else "—")
        c[2].metric("UoA", fmt_pct(k["UoA"].iloc[0]) if k is not None else "—")
        c[3].metric("MTBS (hrs)", fmt_num(r["MTBS"].iloc[0], 1) if r is not None else "—")
        c = st.columns(4)
        c[0].metric("OB (BCM)", fmt_num(summ.get("ob_bcm")))
        c[1].metric("Coal (t)", fmt_num(summ.get("coal_ton"), 1))
        c[2].metric("Fuel (L)", fmt_num(summ.get("fuel_liters")))
        crit = int(dq.get("critical", 0))
        label = f"Data quality: {crit} critical · {int(dq.get('warn', 0))} to check · {int(dq.get('info', 0))} info"
        with st.expander(label, expanded=crit > 0):
            st.dataframe(findings, hide_index=True, width="stretch")

        key = f"us{row['id']}"
        comment = st.text_input("Comment (required when rejecting)", key=f"c_{key}")
        a, _, b = st.columns([1, 4, 1])
        if a.button("Approve", key=f"a_{key}", type="primary"):
            _confirm("approve", row, comment)
        if b.button("Reject", key=f"r_{key}"):
            if not comment.strip():
                st.error("Enter a reason for rejecting.")
            else:
                _confirm("reject", row, comment)
