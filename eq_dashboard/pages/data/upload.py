"""Data_Prod: import a monthly workbook (.xlsb/.xlsx), download the template, export stored data for editing."""
import logging

import pandas as pd
import streamlit as st
from sqlalchemy import select

from auth.access import ADMIN, DATA_OFFICER
from core import dataprod, metrics
from core import ingest as ing
from core.config import today_wib
from core.io import sha256
from core.parse import parse_months
from core.ui import STATUS_BADGE, fmt_num, fmt_pct, require, sites_for
from core.validate import DATASET, TEMPLATE_VERSION, StructureError
from db import models as m
from db import repo
from db.engine import session_scope

MAX_MB = 100  # a whole year of Data_Prod is about 50 MB
log = logging.getLogger("wanpis.import")

user = require("upload")
sites = sites_for(user)
can_import = user.role in (ADMIN, DATA_OFFICER)
st.title(DATASET)
st.caption("The monthly production workbook: time events, trips, weighbridge coal and fuel. "
           "One month per file, or several months (e.g. a year) that are split by month. Uploading a month again "
           "creates a new version and keeps the old one.")

t_imp, t_tpl, t_exp = st.tabs(["Import", "Template", "Export"])

# ------------------------------------------------------------------ import
STEPS = ["Choose file", "Check", "Submit", "Site Manager approval", "Published"]


def stepper(active: int) -> None:
    """Where the user is in the import flow (0-based); the last two steps happen on the Approval page."""
    parts = []
    for i, name in enumerate(STEPS):
        mark = "✓" if i < active else str(i + 1)
        style = ("font-weight:700;color:var(--text-color)" if i == active else
                 "opacity:.55" if i > active else "opacity:.8")
        parts.append(f'<span style="{style}">{mark} {name}</span>')
    st.html('<div style="display:flex;flex-wrap:wrap;gap:.4rem 1.2rem;font-size:.9rem;margin:.2rem 0 .8rem">'
            + '<span style="opacity:.4">→</span>'.join(parts) + "</div>")


def span(df, col="date"):
    if df is None or df.empty:
        return "—"
    d = pd.to_datetime(df[col])
    return f"{d.min():%d %b} – {d.max():%d %b}"


def month_detail(p) -> None:
    """Per sheet and per site figures of one parsed month, with its data quality findings."""
    st.caption(f"Units and sites from {p.population_source}.")
    coal_ok = p.coal[~p.coal["cancelled"]]
    sheets = pd.DataFrame([
        ("Units (population)", len(p.units), "—", f"{(p.units['site'] != 'UNMAPPED').sum():,} with a site"),
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
    for detail in crit["detail"].drop_duplicates().head(5):
        st.error(detail)
    with st.expander(f"Show {len(p.dq)} data quality findings"):
        st.dataframe(p.dq, hide_index=True, width="stretch")


with t_imp:
    if not can_import:
        st.info("Only Admins and Data Officers can import. You can download the template or export data.")
    else:
        f = st.file_uploader(f"Choose a {DATASET} workbook (.xlsb or .xlsx, max {MAX_MB} MB): one month, or several "
                             "months such as a whole year", type=["xlsb", "xlsx"], key="upload_file",
                             max_upload_size=MAX_MB)
        if f is None:
            stepper(0)
            st.session_state.pop("upload_preview", None)
            st.caption(f"Name files {dataprod.file_name(today_wib().replace(day=1), ext='xlsb')}. A file with more "
                       "than one month is split by month; each month is saved and approved on its own. "
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
                        st.write("Checking sheets and columns, splitting by month")
                        with session_scope() as s:
                            results = parse_months(data, alias, tanks,
                                                   population=lambda mo: repo.population_for(s, mo))
                    except StructureError as e:
                        box.update(label="File rejected: the structure does not match the template", state="error")
                        for p_ in e.problems:
                            st.error(p_)
                        st.caption("Download the template from the Template tab to compare sheet and column names.")
                        st.stop()
                    except Exception as e:  # unreadable / corrupt file
                        log.exception("import failed for %s (%s bytes) by %s", f.name, len(data), user.username)
                        box.update(label="File could not be read", state="error")
                        st.error(f"The workbook could not be opened ({type(e).__name__}). Save it again in Excel "
                                 "as .xlsx or .xlsb and retry.")
                        st.stop()
                    multi = len(results) > 1
                    digests = {r.month: ing.month_digest(data, r.month) if multi else digest for r in results}
                    with session_scope() as s:
                        done = dict(s.execute(select(m.Upload.sha256, m.Upload.id)
                                              .where(m.Upload.sha256.in_(list(digests.values())))).all())
                    ok = sum(r.parsed is not None for r in results)
                    box.update(label=f"Workbook read: {len(results)} month(s), {ok} readable", state="complete",
                               expanded=False)
                prev = {"digest": digest, "results": results, "digests": digests, "done": done, "name": f.name}
                st.session_state["upload_preview"] = prev

            results, digests, done = prev["results"], prev["digests"], prev["done"]
            stepper(1)
            if len(results) == 1:
                r = results[0]
                if r.parsed is None:
                    for p_ in r.problems:
                        st.error(p_)
                    st.stop()
                warn = dataprod.name_check(prev["name"], r.month)
                if warn:
                    st.warning(warn)
                st.subheader(f"Check · {r.month:%B %Y}")
                month_detail(r.parsed)
                chosen = [r]
            else:
                st.subheader(f"Check · {len(results)} months, {results[0].month:%b %Y} – {results[-1].month:%b %Y}")
                table = []
                for r in results:
                    p = r.parsed
                    if p is None:
                        state = "cannot be read"
                    elif digests[r.month] in done:
                        state = f"already uploaded (#{done[digests[r.month]]})"
                    else:
                        state = "critical findings" if (p.dq["severity"] == "critical").any() else "ready"
                    sev = p.dq["severity"].value_counts() if p is not None else pd.Series(dtype=int)
                    table.append({
                        "Month": f"{r.month:%b %Y}", "Status": state,
                        "Events": len(p.events) if p is not None else 0,
                        "OB (BCM)": fmt_num(p.ritase.loc[p.ritase.material_group == "OB", "volume"].sum())
                        if p is not None else "—",
                        "Coal (t)": fmt_num(p.coal.loc[~p.coal["cancelled"], "ton"].sum(), 1) if p is not None else "—",
                        "Fuel (L)": fmt_num(p.fuel["liters"].sum()) if p is not None else "—",
                        "Sites": ", ".join(p.sites) if p is not None else "",
                        "DQ critical": int(sev.get("critical", 0)), "DQ check": int(sev.get("warn", 0)),
                    })
                st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
                can = [r for r in results if r.parsed is not None and digests[r.month] not in done]
                labels = {f"{r.month:%b %Y}": r for r in can}
                picked = st.multiselect("Months to submit", list(labels), default=list(labels), key="upload_months",
                                        help="Each month becomes its own upload and is approved per site on its own.")
                chosen = [labels[x] for x in picked]
                look = st.selectbox("Details of month", [f"{r.month:%b %Y}" for r in results], key="upload_look")
                r = next(x for x in results if f"{x.month:%b %Y}" == look)
                with st.container(border=True):
                    if r.parsed is None:
                        for p_ in r.problems:
                            st.error(p_)
                    else:
                        month_detail(r.parsed)

            crit = [r for r in chosen if (r.parsed.dq["severity"] == "critical").any()]
            if crit:
                st.warning(f"{len(crit)} month(s) with critical findings. Sites with critical findings are never "
                           "auto-approved and wait for Site Manager approval. Fixing the file first is better.")
            label = "Submit for approval" if len(chosen) <= 1 else f"Submit {len(chosen)} months for approval"
            if st.button(label, type="primary", disabled=not chosen):
                saved = []
                bar = st.progress(0.0, text="Saving to the database…")
                for i, r in enumerate(chosen, 1):
                    name = prev["name"] if len(results) == 1 else f"{prev['name']} [{r.month:%Y-%m}]"
                    try:
                        with session_scope() as s:
                            up, ups = ing.ingest(s, data, name, user.id, user.username, parsed=r.parsed,
                                                 digest=digests[r.month])
                            saved.append((r.month, up.id, [(us.site_code, us.status) for us in ups]))
                    except ing.DuplicateUpload as e:
                        st.error(f"{r.month:%b %Y}: {e}")
                    bar.progress(i / len(chosen), text=f"Saved {r.month:%b %Y}")
                bar.empty()
                st.session_state.pop("upload_preview", None)
                st.cache_data.clear()
                stepper(3)
                for mo, up_id, result in saved:
                    st.markdown(f"**{mo:%B %Y}** · upload #{up_id}: "
                                + " · ".join(f"{site} {STATUS_BADGE[status]}" for site, status in result))
                if saved:
                    st.success(f"{len(saved)} month(s) saved. Pending sites now wait in **Approval**; approved sites "
                               "appear on the dashboards at once.")

# ------------------------------------------------------------------ template
with t_tpl:
    st.markdown(
        f"A blank **{DATASET}** workbook (template version {TEMPLATE_VERSION}) with the exact sheets and headers the "
        "app expects, a README with every column explained, drop-down lists for Shift, Status and Site, "
        "and input checks on dates, times and numbers. Hover a header in Excel to see its description.")
    real_sites = [x for x in sites if x != "UNMAPPED"]
    # deferred: every tab runs on every rerun, so build the workbook only when the button is clicked
    st.download_button("Download template (.xlsx)", lambda: dataprod.build_template(real_sites),
                       file_name=f"{DATASET}_template_v{TEMPLATE_VERSION}.xlsx", type="primary",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", on_click="ignore")
    st.caption("Units and their sites are no longer part of Data_Prod: keep them in the Unit_Population workbook "
               "(Data → Unit population).")
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
