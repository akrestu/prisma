"""Data_Prod: import a monthly workbook (.xlsb/.xlsx), download the template, export stored data for editing."""
import pandas as pd
import streamlit as st
from sqlalchemy import select

from auth.access import ADMIN, DATA_OFFICER
from core import dataprod, metrics
from core import ingest as ing
from core.config import today_wib
from core.io import sha256
from core.parse import parse_data_prod
from core.ui import STATUS_BADGE, fmt_num, fmt_pct, require, sites_for
from core.validate import DATASET, TEMPLATE_VERSION, StructureError
from db import models as m
from db import repo
from db.engine import session_scope

MAX_MB = 50

user = require("upload")
sites = sites_for(user)
can_import = user.role in (ADMIN, DATA_OFFICER)
st.title(DATASET)
st.caption("The monthly production workbook: time events, trips, weighbridge coal and fuel. "
           "One file = one month; uploading the same month again creates a new version and keeps the old one.")

t_imp, t_tpl, t_exp = st.tabs(["Import", "Template", "Export"])

# ------------------------------------------------------------------ import
with t_imp:
    if not can_import:
        st.info("Only Admins and Data Officers can import. You can download the template or export data.")
    else:
        f = st.file_uploader(f"Choose a {DATASET} workbook (.xlsb or .xlsx, max {MAX_MB} MB)", type=["xlsb", "xlsx"],
                             key="upload_file", max_upload_size=MAX_MB)
        if f is None:
            st.session_state.pop("upload_preview", None)
            st.caption(f"Name files {dataprod.file_name(today_wib().replace(day=1), ext='xlsb')}. "
                       "Nothing is saved until you press Submit.")
        else:
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
                with st.status("Checking and reading the workbook…", expanded=True) as box:
                    try:
                        st.write("Checking sheets and columns")
                        parsed = parse_data_prod(data, alias, tanks)
                    except StructureError as e:
                        box.update(label="File rejected: the structure does not match the template", state="error")
                        for p_ in e.problems:
                            st.error(p_)
                        st.caption("Download the template from the Template tab to compare sheet and column names.")
                        st.stop()
                    except Exception as e:  # unreadable / corrupt file
                        box.update(label="File could not be read", state="error")
                        st.error(f"The workbook could not be opened ({type(e).__name__}). Save it again in Excel "
                                 "as .xlsx or .xlsb and retry.")
                        st.stop()
                    box.update(label=f"Workbook read: {parsed.month:%B %Y}, {len(parsed.events):,} event rows",
                               state="complete", expanded=False)
                prev = {"digest": digest, "parsed": parsed, "name": f.name}
                st.session_state["upload_preview"] = prev

            p = prev["parsed"]
            warn = dataprod.name_check(prev["name"], p.month)
            if warn:
                st.warning(warn)

            st.subheader(f"Check · {p.month:%B %Y}")

            def span(df, col="date"):
                if df is None or df.empty:
                    return "—"
                d = pd.to_datetime(df[col])
                return f"{d.min():%d %b} – {d.max():%d %b}"

            coal_ok = p.coal[~p.coal["cancelled"]]
            sheets = pd.DataFrame([
                ("Populasi Unit", len(p.units), "—", f"{(p.units['site'] != 'UNMAPPED').sum():,} with a site"),
                ("Eq.Event", len(p.events), span(p.events), f"{p.events['unit_id'].nunique():,} units"),
                ("Ritasi Unit", int(p.ritase["rit"].sum()), span(p.ritase),
                 f"OB {fmt_num(p.ritase.loc[p.ritase.material_group == 'OB', 'volume'].sum())} BCM (trips)"),
                ("Data Timbangan", len(coal_ok), span(coal_ok), f"{fmt_num(coal_ok['ton'].sum(), 1)} t"),
                ("Fuel Consume", len(p.fuel), span(p.fuel), f"{fmt_num(p.fuel['liters'].sum())} L"),
                ("Fuel Receipt", len(p.receipt), span(p.receipt), f"{fmt_num(p.receipt['liters'].sum())} L"),
            ], columns=["Sheet", "Rows", "Dates", "Total"])
            st.dataframe(sheets, hide_index=True, width="stretch")

            rows = []
            for site in p.sites:
                summ = ing.site_summary(p, site)
                k = metrics.kpis(p.events[p.events["site"] == site])
                dq = p.dq[p.dq["site"] == site]["severity"].value_counts()
                rows.append({"Site": site, "Units": summ["units"],
                             "PA (%)": fmt_pct(k["PA"].iloc[0] if len(k) else None),
                             "UoA (%)": fmt_pct(k["UoA"].iloc[0] if len(k) else None),
                             "OB (BCM)": fmt_num(summ["ob_bcm"]), "Coal (t)": fmt_num(summ["coal_ton"], 1),
                             "Fuel (L)": fmt_num(summ["fuel_liters"]), "DQ critical": int(dq.get("critical", 0)),
                             "DQ check": int(dq.get("warn", 0)), "DQ info": int(dq.get("info", 0))})
            st.markdown("**Per site** (what each Site Manager will approve)")
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
                            up, ups = ing.ingest(s, data, prev["name"], user.id, user.username, parsed=p)
                            result = [(us.site_code, us.status) for us in ups]
                            up_id = up.id
                    except ing.DuplicateUpload as e:
                        st.error(str(e))
                        st.stop()
                st.session_state.pop("upload_preview", None)
                st.success(f"Upload #{up_id} saved.")
                for site, status in result:
                    st.markdown(f"- **{site}** {STATUS_BADGE[status]}")
                st.cache_data.clear()

# ------------------------------------------------------------------ template
with t_tpl:
    st.markdown(
        f"A blank **{DATASET}** workbook (template version {TEMPLATE_VERSION}) with the exact sheets and headers the "
        "app expects, a README with every column explained, drop-down lists for Shift, Status and Site, "
        "and input checks on dates, times and numbers. Hover a header in Excel to see its description.")
    prefill = st.checkbox("Pre-fill 'Populasi Unit' with the latest unit list of my sites", value=True, key="tpl_units")
    real_sites = [x for x in sites if x != "UNMAPPED"]
    with session_scope() as s:
        units = repo.latest_units(s, real_sites) if prefill else None
    # deferred: every tab runs on every rerun, so build the workbook only when the button is clicked
    st.download_button("Download template (.xlsx)", lambda: dataprod.build_template(real_sites, units),
                       file_name=f"{DATASET}_template_v{TEMPLATE_VERSION}.xlsx", type="primary",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", on_click="ignore")
    st.caption("Your existing .xlsb files keep working: the template only fixes names and formats, it does not "
               "change how data is calculated.")

# ------------------------------------------------------------------ export
with t_exp:
    with session_scope() as s:
        pub = repo.published_versions(s, sites)
    if pub.empty:
        st.info("No PUBLISHED data to export yet.")
    else:
        st.markdown(f"Export PUBLISHED data back into a **{DATASET}** workbook in the template format. Correct it in "
                    "Excel and import it again to create a new version (stoppages and data quality are recalculated).")
        c1, c2 = st.columns(2)
        months = sorted(pub["month"].unique(), reverse=True)
        month = c1.selectbox("Month", months, format_func=lambda d: pd.Timestamp(d).strftime("%B %Y"), key="exp_month")
        opts = sorted(pub[pub["month"] == month]["site"].unique())
        chosen = c2.multiselect("Site", opts, default=opts, key="exp_sites")
        v = pub[(pub["month"] == month) & pub["site"].isin(chosen)]
        mdate = pd.Timestamp(month).date()
        name = dataprod.file_name(mdate, chosen[0] if len(chosen) == 1 else None)

        def build_export() -> bytes:
            """Runs only when the button is clicked (≈10 s for a full month); nothing is kept in session memory."""
            with session_scope() as s:
                tables = repo.export_tables(s, [(int(r.upload_id), r.site) for r in v.itertuples()])
            return dataprod.export_workbook(tables, mdate, chosen)

        if chosen:
            st.download_button(f"Download {name}", build_export, file_name=name, type="primary", on_click="ignore",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key="exp_dl")
            st.caption("Building a full month takes about 10 seconds after you click.")
