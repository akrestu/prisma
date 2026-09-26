"""Upload an Eq.Event file: structure check → per-site preview + data quality → Submit."""
import pandas as pd
import streamlit as st
from sqlalchemy import select

from core import ingest as ing
from core import metrics
from core.io import sha256
from core.parse import parse_eq_event
from core.ui import STATUS_BADGE, fmt_num, fmt_pct, require
from core.validate import StructureError
from db import models as m
from db.engine import session_scope

user = require("upload")
st.title("Upload Eq.Event data")
st.caption("One file = one month (month to date). Uploading the same month again creates a new version; "
           "older versions are kept.")

f = st.file_uploader("Choose an Eq.Event file (.xlsb)", type=["xlsb"], key="upload_file")
if f is None:
    st.session_state.pop("upload_preview", None)
    st.stop()

data = f.getvalue()
digest = sha256(data)
prev = st.session_state.get("upload_preview")
if prev is None or prev["digest"] != digest:
    with session_scope() as s:
        dup = s.scalar(select(m.Upload.id).where(m.Upload.sha256 == digest))
        alias, tanks = ing.lookups(s)
    if dup:
        st.error(f"This file is identical to upload #{dup}. No need to upload it again.")
        st.stop()
    with st.status("Checking and reading the file…", expanded=True) as box:
        try:
            st.write("Checking sheets and columns")
            parsed = parse_eq_event(data, alias, tanks)
        except StructureError as e:
            box.update(label="File rejected: invalid structure", state="error")
            for p in e.problems:
                st.error(p)
            st.stop()
        box.update(label=f"File read: {parsed.month:%B %Y}, {len(parsed.events):,} event rows",
                   state="complete", expanded=False)
    prev = {"digest": digest, "parsed": parsed, "name": f.name}
    st.session_state["upload_preview"] = prev

p = prev["parsed"]
st.subheader(f"Preview · {p.month:%B %Y}")
rows = []
for site in p.sites:
    summ = ing.site_summary(p, site)
    k = metrics.kpis(p.events[p.events["site"] == site])
    dq = p.dq[p.dq["site"] == site]["severity"].value_counts()
    rows.append({"Site": site, "Units": summ["units"], "PA": fmt_pct(k["PA"].iloc[0] if len(k) else None),
                 "UoA": fmt_pct(k["UoA"].iloc[0] if len(k) else None), "OB (BCM)": fmt_num(summ["ob_bcm"]),
                 "Coal (t)": fmt_num(summ["coal_ton"], 1), "Fuel (L)": fmt_num(summ["fuel_liters"]),
                 "DQ critical": int(dq.get("critical", 0)), "DQ check": int(dq.get("warn", 0)),
                 "DQ info": int(dq.get("info", 0))})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

crit = p.dq[p.dq["severity"] == "critical"]
if len(crit):
    st.warning(f"{len(crit)} critical finding(s). Sites with critical findings are never auto-approved "
               "and wait for Site Manager approval.")
with st.expander(f"Show {len(p.dq)} data quality findings"):
    st.dataframe(p.dq, hide_index=True, width="stretch")

if st.button("Submit for approval", type="primary"):
    with st.spinner("Saving to the database…"):
        try:
            with session_scope() as s:
                up, sites = ing.ingest(s, data, prev["name"], user.id, user.username, parsed=p)
                result = [(us.site_code, us.status) for us in sites]
                up_id = up.id
        except ing.DuplicateUpload as e:
            st.error(str(e))
            st.stop()
    st.session_state.pop("upload_preview", None)
    st.success(f"Upload #{up_id} saved.")
    for site, status in result:
        st.markdown(f"- **{site}** {STATUS_BADGE[status]}")
    st.cache_data.clear()
