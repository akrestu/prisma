"""Approval queue per site: KPI preview + data quality → Approve / Reject."""
import streamlit as st

from auth.access import can_review
from core import ingest as ing
from core import dash, metrics
from core.ui import fmt_num, fmt_pct, require, sites_for
from db import models as m
from db import repo
from db.engine import session_scope

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

for _, row in queue.iterrows():
    dq = row["dq_summary"] or {}
    summ = row["summary"] or {}
    head = (f"**{row['site']}** · {row['month']:%B %Y} · upload #{row['upload_id']} · {row['filename']} · "
            f"by {row['uploader'] or '-'}")
    with st.container(border=True):
        st.markdown(head)
        with session_scope() as s:
            ev = repo.events(s, int(row["upload_id"]), row["site"])
            st_ = repo.stoppages(s, int(row["upload_id"]), row["site"])
            findings = repo.dq_findings(s, int(row["upload_id"]), row["site"])
        k = metrics.kpis(ev) if len(ev) else None
        r = metrics.reliability(ev, st_) if len(ev) else None
        c = st.columns(7)
        c[0].metric("Units", summ.get("units", 0))
        c[1].metric("PA", fmt_pct(k["PA"].iloc[0]) if k is not None else "—")
        c[2].metric("UoA", fmt_pct(k["UoA"].iloc[0]) if k is not None else "—")
        c[3].metric("MTBS (hrs)", fmt_num(r["MTBS"].iloc[0], 1) if r is not None else "—")
        c[4].metric("OB (BCM)", fmt_num(summ.get("ob_bcm")))
        c[5].metric("Coal (t)", fmt_num(summ.get("coal_ton"), 1))
        c[6].metric("Fuel (L)", fmt_num(summ.get("fuel_liters")))
        crit = int(dq.get("critical", 0))
        label = f"Data quality: {crit} critical · {int(dq.get('warn', 0))} to check · {int(dq.get('info', 0))} info"
        with st.expander(label, expanded=crit > 0):
            st.dataframe(findings, hide_index=True, width="stretch")

        key = f"us{row['id']}"
        comment = st.text_input("Comment (required when rejecting)", key=f"c_{key}")
        a, b, _ = st.columns([1, 1, 4])
        if a.button("Approve", key=f"a_{key}", type="primary"):
            with session_scope() as s:
                ing.publish(s, s.get(m.UploadSite, int(row["id"])), user.id, user.username, comment=comment)
            st.cache_data.clear()
            st.toast(f"{row['site']} {row['month']:%Y-%m} PUBLISHED")
            st.rerun()
        if b.button("Reject", key=f"r_{key}"):
            if not comment.strip():
                st.error("Enter a reason for rejecting.")
            else:
                with session_scope() as s:
                    ing.reject(s, s.get(m.UploadSite, int(row["id"])), user.id, user.username, comment)
                st.toast(f"{row['site']} rejected")
                st.rerun()
