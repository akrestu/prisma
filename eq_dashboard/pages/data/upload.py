"""Production Data: import a monthly or yearly workbook (.xlsb/.xlsx), correct a month in the Edit grids, download
the template, export stored data. Every import or edit becomes a new version per site × month that is approved."""
import logging

import pandas as pd
import streamlit as st
from sqlalchemy import select

from auth.access import ADMIN, DATA_OFFICER
from core import dataprod, metrics
from core import ingest as ing
from core.config import UNMAPPED, today_wib
from core.io import sha256
from core.parse import parse_months
from core.ui import STATUS_BADGE, fmt_num, fmt_pct, require, sites_for
from core.validate import DATA_SHEETS, DATASET, EVENTS, SHEET_BY_NAME, TEMPLATE_VERSION, StructureError, file_stem
from db import models as m
from db import repo
from db.engine import session_scope

MAX_MB = 100  # a whole year of Production Data is about 50 MB
log = logging.getLogger("wanpis.import")

user = require("upload")
sites = sites_for(user)
can_import = user.role in (ADMIN, DATA_OFFICER)
st.title(DATASET)
st.caption("Equipment events, hauler trips, coal weighbridge and fuel. Import one month or a whole year (split by "
           "month), or correct a month in the Edit tab. Every import or edit becomes a new version per site × month "
           "that a Site Manager approves; the previous version is kept.")

msg = st.session_state.pop("pe_msg", None)
if msg:
    st.success(msg)

t_imp, t_edit, t_tpl, t_exp = st.tabs(["Import", "Edit", "Template", "Export"])

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
        ("Equipment Events", len(p.events), span(p.events), f"{p.events['unit_id'].nunique():,} units"),
        ("Hauler Trips", int(p.ritase["rit"].sum()), span(p.ritase),
         f"OB {fmt_num(p.ritase.loc[p.ritase.material_group == 'OB', 'volume'].sum())} BCM (trips)"),
        ("Coal Weighbridge", len(coal_ok), span(coal_ok), f"{fmt_num(coal_ok['ton'].sum(), 1)} t"),
        ("Fuel Consumption", len(p.fuel), span(p.fuel), f"{fmt_num(p.fuel['liters'].sum())} L"),
        ("Fuel Receipts", len(p.receipt), span(p.receipt), f"{fmt_num(p.receipt['liters'].sum())} L"),
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
        f = st.file_uploader(f"Choose a {DATASET} workbook (.xlsb or .xlsx, max {MAX_MB} MB): one month, or a whole "
                             "year", type=["xlsb", "xlsx"], key="upload_file",
                             max_upload_size=MAX_MB)
        if f is None:
            stepper(0)
            st.session_state.pop("upload_preview", None)
            st.caption(f"Name files {dataprod.file_name(today_wib().replace(day=1), ext='xlsb')} (a month) or "
                       f"{file_stem(DATASET)}_{today_wib():%Y}.xlsb (a year). A file with more than one month is split "
                       "by month; each month is saved and approved on its own. Nothing is saved until you press "
                       "Submit.")
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
                bar = st.progress(0.0, text=f"Saving {len(chosen)} month(s) to the database…")
                for i, r in enumerate(chosen, 1):
                    name = prev["name"] if len(results) == 1 else f"{prev['name']} [{r.month:%Y-%m}]"
                    try:
                        with session_scope() as s:
                            up, ups = ing.ingest(s, data, name, user.id, user.username, parsed=r.parsed,
                                                 digest=digests[r.month])
                            saved.append((r.month, up.id, [(us.site_code, us.status) for us in ups]))
                    except ing.DuplicateUpload as e:
                        st.error(f"{r.month:%b %Y}: {e}")
                    bar.progress(i / len(chosen), text=f"Saved {r.month:%b %Y} ({i} of {len(chosen)})")
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

# ------------------------------------------------------------------ edit (manual correction → new version)
def column_config(sheet: str) -> dict:
    """Grid columns typed like the template, with the template's description as help."""
    out = {}
    for c in SHEET_BY_NAME[sheet].cols:
        tip = c.desc + (f" ({', '.join(c.choices)})" if c.choices else "")
        if c.kind == "date":
            out[c.name] = st.column_config.DateColumn(c.name, help=tip, format="YYYY-MM-DD")
        elif c.kind == "time":
            out[c.name] = st.column_config.TimeColumn(c.name, help=tip, format="HH:mm")
        elif c.kind == "datetime":
            out[c.name] = st.column_config.DatetimeColumn(c.name, help=tip, format="YYYY-MM-DD HH:mm")
        elif c.kind in ("number", "int"):
            out[c.name] = st.column_config.NumberColumn(c.name, help=tip, min_value=0,
                                                        step=1 if c.kind == "int" else None,
                                                        format="%d" if c.kind == "int" else None)
        else:
            out[c.name] = st.column_config.TextColumn(c.name, help=tip)
    return out


def differs(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    if len(a) != len(b):
        return True
    norm = lambda d: d.reset_index(drop=True).astype(str).replace({"NaT": "", "nan": "", "None": ""})  # noqa: E731
    return not norm(a).equals(norm(b))


def typed(df: pd.DataFrame, sheet: str) -> pd.DataFrame:
    """Date columns as dates (DateColumn needs them), so a value the grid did not touch keeps its type."""
    df = df.copy()
    for c in SHEET_BY_NAME[sheet].cols:
        if c.kind == "date" and c.name in df:
            df[c.name] = pd.to_datetime(df[c.name], errors="coerce").dt.date
        elif c.kind == "datetime" and c.name in df:
            df[c.name] = pd.to_datetime(df[c.name], errors="coerce")
    return df


with t_edit:
    if not can_import:
        st.info("Only Admins and Data Officers can edit. Site Managers approve the result in Approval.")
    else:
        with session_scope() as s:
            pub = repo.published_versions(s, sites)
        pub = pub[pub["site"] != UNMAPPED]
        if pub.empty:
            st.info(f"No PUBLISHED {DATASET} yet. Import a workbook first; once approved, a month can be corrected "
                    "here.")
        else:
            st.caption("Correct a published month without Excel: change cells, add or delete rows, then submit. "
                       "The month is checked exactly like an import and saved as a new version that waits for "
                       "approval; the published version stays on the dashboards until then.")
            c1, c2 = st.columns(2)
            site = c1.selectbox("Site", sorted(pub["site"].unique()), key="pe_site")
            months = sorted(pub.loc[pub["site"] == site, "month"].unique(), reverse=True)
            month = c2.selectbox("Month", months, format_func=lambda d: pd.Timestamp(d).strftime("%B %Y"),
                                 key="pe_month")
            month = pd.Timestamp(month).date()
            up_id = int(pub.loc[(pub["site"] == site) & (pub["month"] == month), "upload_id"].iloc[0])
            key = (up_id, site)
            work = st.session_state.get("pe_work")
            if work is None or work["key"] != key:
                with st.spinner(f"Loading {site} · {month:%B %Y}…"):
                    with session_scope() as s:
                        tables = repo.export_tables(s, [key])
                    frames = {k: typed(v, k) for k, v in dataprod.export_frames(tables).items()}
                work = {"key": key, "orig": frames, "edit": dict(frames), "base": dict(frames),
                        "ver": dict.fromkeys(frames, 0)}
                st.session_state["pe_work"] = work
                st.session_state.pop("pe_last", None)

            names = [sh.name for sh in DATA_SHEETS]
            changed = [n for n in names if differs(work["edit"][n], work["orig"][n])]
            sheet = st.segmented_control(
                "Sheet", names, default=EVENTS, key="pe_sheet",
                format_func=lambda n: f"{n} ({len(work['edit'][n]):,})" + (" •" if n in changed else "")) or EVENTS
            if st.session_state.get("pe_last") != sheet:
                # a grid that was hidden lost its widget state: restart it from the edits kept so far
                work["ver"][sheet] += 1
                work["base"][sheet] = work["edit"][sheet]
                st.session_state["pe_last"] = sheet
            edited = st.data_editor(work["base"][sheet], num_rows="dynamic", hide_index=True, width="stretch",
                                    height=460, column_config=column_config(sheet),
                                    key=f"pe_grid_{up_id}_{site}_{sheet}_{work['ver'][sheet]}")
            work["edit"][sheet] = edited
            changed = [n for n in names if differs(work["edit"][n], work["orig"][n])]
            st.caption("Click a header to sort; use the search icon above the grid to find a unit or ticket. "
                       "Select rows on the left edge and press Delete to remove them; add rows at the bottom.")

            if changed:
                st.warning(f"Unsaved changes in: {', '.join(changed)}. Changing the site or month discards them.")
            note = st.text_input("Reason for the change (required)", key="pe_note", max_chars=120,
                                 placeholder="e.g. WHT026 hours on 12 Sep entered twice")
            a, b, _ = st.columns([1.4, 1, 3])
            submit = a.button("Submit as new version", type="primary", key="pe_submit",
                              disabled=not changed or not note.strip())
            if b.button("Discard changes", key="pe_discard", disabled=not changed):
                st.session_state.pop("pe_work", None)
                st.rerun()
            if submit:
                problems: list[str] = []
                with st.status(f"Checking and saving {site} · {month:%B %Y}…", expanded=True) as box:
                    st.write("Building the workbook from the grids")
                    data = dataprod.frames_workbook(work["edit"], month, [site])
                    st.write("Checking structure and data quality (same checks as an import)")
                    with session_scope() as s:
                        alias, tanks = ing.lookups(s)
                        try:
                            results = parse_months(data, alias, tanks,
                                                   population=lambda mo: repo.population_for(s, mo))
                        except StructureError as e:
                            results, problems = [], e.problems
                    if len(results) != 1 or results[0].parsed is None or results[0].month != month:
                        box.update(label="Not saved: the edited month does not pass the checks", state="error")
                        if len(results) > 1:
                            problems = [f"Some dates moved out of {month:%B %Y} "
                                        f"({', '.join(f'{r.month:%b %Y}' for r in results)}). Keep every date in "
                                        "the month you edit."]
                        elif results:
                            problems = results[0].problems or [f"The rows are not in {month:%B %Y}."]
                        for p_ in problems:
                            st.error(p_)
                        st.stop()
                    p = results[0].parsed
                    if site not in p.sites:
                        box.update(label="Not saved", state="error")
                        st.error(f"No rows of {month:%B %Y} belong to {site} any more.")
                        st.stop()
                    st.write("Saving the new version")
                    with session_scope() as s:
                        up, ups = ing.ingest(s, data, f"Manual edit · {site} {month:%Y-%m} · {note.strip()}"[:250],
                                             user.id, user.username, parsed=p, sites=[site])
                        ing.audit(s, user.username, "manual_edit", site,
                                  f"{month:%Y-%m} upload #{up.id} (from #{up_id}): {', '.join(changed)} · {note}")
                        status, up_new = ups[0].status, up.id
                    box.update(label="Saved", state="complete", expanded=False)
                crit = int((p.dq.loc[p.dq["site"] == site, "severity"] == "critical").sum())
                st.cache_data.clear()
                st.session_state.pop("pe_work", None)
                st.session_state["pe_msg"] = (
                    f"{site} · {month:%B %Y} saved as upload #{up_new} ({status}). "
                    + ("It is already PUBLISHED (auto-approve)." if status == "PUBLISHED" else
                       "It waits in Approval; the current version stays on the dashboards until it is approved.")
                    + (f" {crit} critical data quality finding(s): check them before approving." if crit else ""))
                st.rerun()

# ------------------------------------------------------------------ template
with t_tpl:
    st.markdown(
        f"A blank **{DATASET}** workbook (template version {TEMPLATE_VERSION}) with the exact sheets and headers the "
        "app expects, a README with every column explained, drop-down lists for Shift, Status and Site, "
        "and input checks on dates, times and numbers. Hover a header in Excel to see its description.")
    real_sites = [x for x in sites if x != "UNMAPPED"]
    # deferred: every tab runs on every rerun, so build the workbook only when the button is clicked
    st.download_button("Download template (.xlsx)", lambda: dataprod.build_template(real_sites),
                       file_name=f"{file_stem(DATASET)}_template_v{TEMPLATE_VERSION}.xlsx", type="primary",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", on_click="ignore")
    st.caption("Units and their sites are not part of Production Data: keep them in the Unit Population workbook "
               "(Input & upload → Unit Population).")
    st.caption("Your existing files keep working: the old sheet names (Eq.Event, Ritasi Unit, Data Timbangan, "
               "Fuel Consume, Fuel Receipt) and Data_Prod file names are still read. The template only fixes names "
               "and formats, it does not change how data is calculated.")

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
