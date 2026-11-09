"""Data explorer: read-only raw rows per table, filtered by version, site, dates and text; CSV / Excel download."""
import pandas as pd
import streamlit as st

from auth.access import ADMIN, DATA_OFFICER, SITE_MANAGER, can_review
from core import dash
from core import ingest as ing
from core.ui import excel_bytes, fmt_num, require, sites_for
from db import repo
from db.engine import session_scope

EXCEL_MAX = 100_000  # bigger results download as CSV only (Excel gets slow and heavy)
DOWNLOAD_MAX = 200_000
PAGE_ROWS = 2_000    # rows sent to the browser per page

user = require("data_explorer")
sites = sites_for(user)
st.title("Data explorer")
st.caption("Browse, filter and download the stored data tables.")

with session_scope() as s:
    pub = repo.published_versions(s, sites)
    pending = repo.upload_sites(s, sites, [ing.PENDING]) if user.role in (ADMIN, SITE_MANAGER, DATA_OFFICER) \
        else pd.DataFrame()
if len(pending):
    if user.role == DATA_OFFICER:
        pending = pending[pending["uploaded_by"] == user.id]
    elif user.role == SITE_MANAGER:
        pending = pending[[can_review(user, x, sites) for x in pending["site"]]]

a, b = st.columns([1, 2])
source = a.segmented_control("Data", ["Published", "Pending"] if len(pending) else ["Published"],
                             default="Published", key="dx_source") or "Published"
table = b.selectbox("Table", list(repo.EXPLORER_TABLES), key="dx_table")

if source == "Published":
    if pub.empty:
        st.info("No PUBLISHED data yet.")
        st.stop()
    c1, c2 = st.columns(2)
    site_opts = sorted(pub["site"].unique())
    sel_sites = c1.multiselect("Site", site_opts, default=site_opts, key="dx_site")
    month_opts = sorted(pub[pub["site"].isin(sel_sites)]["month"].unique(), reverse=True)
    sel_months = c2.multiselect("Month", month_opts, default=month_opts[:1],
                                format_func=lambda d: pd.Timestamp(d).strftime("%B %Y"), key="dx_month")
    v = pub[pub["site"].isin(sel_sites) & pub["month"].isin(sel_months)]
    versions = [(int(r.upload_id), r.site) for r in v.itertuples()]
    label = ", ".join(pd.Timestamp(x).strftime("%b %Y") for x in sorted(sel_months)) or "no month"
else:
    opts = {int(r.id): r for r in pending.itertuples()}
    pick = st.selectbox("Pending upload", list(opts), key="dx_pending", format_func=lambda i: (
        f"{opts[i].site} · {pd.Timestamp(opts[i].month):%B %Y} · upload #{opts[i].upload_id} · {opts[i].filename}"))
    r = opts[pick]
    versions = [(int(r.upload_id), r.site)]
    label = f"PENDING upload #{r.upload_id}"
    st.caption("Not approved yet: this data is not visible on dashboards or TVs.")

if not versions:
    st.info("Choose at least one site and month.")
    st.stop()

@st.cache_data(ttl=600, max_entries=60, show_spinner=False)
def _dates(table: str, versions: tuple[tuple[int, str], ...]) -> tuple | None:
    with session_scope() as s:
        return repo.explorer_dates(s, table, list(versions))


@st.cache_data(ttl=600, max_entries=60, show_spinner=False)
def _count(table: str, versions: tuple[tuple[int, str], ...], d0, d1, unit: str, search: str) -> int:
    with session_scope() as s:
        return repo.explorer_count(s, table, list(versions), d0, d1, unit, search)


@st.cache_data(ttl=600, max_entries=60, show_spinner=False)
def _page(table: str, versions: tuple[tuple[int, str], ...], d0, d1, unit: str, search: str, offset: int) -> pd.DataFrame:
    """One page of rows, cached per table × versions × filters (never per user: `versions` is already limited to what
    this user may see). The filters run in the database; only the page shown leaves it."""
    with session_scope() as s:
        return repo.explorer_rows(s, table, list(versions), d0, d1, PAGE_ROWS, unit, search, offset)


def tidy(rows: pd.DataFrame) -> pd.DataFrame:
    """Source row in the Excel sheet first: find the original line quickly."""
    if "row_ref" not in rows.columns:
        return rows
    return rows[["row_ref", *[c for c in rows.columns if c != "row_ref"]]].rename(columns={"row_ref": "Excel row"})


def everything() -> pd.DataFrame:
    """Every filtered row, read only when a download button is pressed."""
    with session_scope() as s:
        return tidy(repo.explorer_rows(s, table, list(key_versions), d0, d1, DOWNLOAD_MAX, units, text))


key_versions = tuple(sorted(versions))
f1, f2, f3 = st.columns([1.3, 1, 1.7])
d0 = d1 = None
bounds = _dates(table, key_versions)
if bounds:
    rng = f1.date_input("Dates", bounds, min_value=bounds[0], max_value=bounds[1], key=f"dx_dates_{table}_{label}")
    if isinstance(rng, (tuple, list)) and len(rng) == 2:
        d0, d1 = rng
units = f2.text_input("Unit ID", key="dx_unit", placeholder="e.g. WEX019").strip()
text = f3.text_input("Search all columns", key="dx_text", placeholder="reason, material, ticket, seam…").strip()
total = _count(table, key_versions, d0, d1, units, text)

# only one page of rows goes to the browser; downloads read every filtered row when pressed
pages = max(1, -(-total // PAGE_ROWS))
page = 1
dash.summary(f"{fmt_num(total)} rows of {table.lower()}", label,
             f"{len({s_ for _, s_ in versions})} site(s)")
if total > DOWNLOAD_MAX:
    st.warning(f"Downloads hold the first {DOWNLOAD_MAX:,} rows. Narrow the months or sites to download everything.")
if pages > 1:
    p1, p2 = st.columns([1, 5])
    page = int(p1.number_input("Page", 1, pages, 1, key=f"dx_page_{table}_{label}"))
    p2.caption(f"Rows {(page - 1) * PAGE_ROWS + 1:,}–{min(page * PAGE_ROWS, total):,} of {total:,}")
with st.spinner(f"Loading {table.lower()}…"):
    df = tidy(_page(table, key_versions, d0, d1, units, text, (page - 1) * PAGE_ROWS))
if "Excel row" in df.columns and len(df) and df["Excel row"].isna().all() and table != "Data quality findings":
    st.caption("Excel row numbers are stored for files imported from 28 Sep 2026 on; import older months "
               "again to fill them in.")

st.dataframe(df, hide_index=True, width="stretch", height=560)

fname = table.split(" (")[0].lower().replace(" ", "_")
c1, c2, _ = st.columns([1, 1, 4])
c1.download_button("Download CSV", lambda: everything().to_csv(index=False).encode("utf-8-sig"), f"{fname}.csv", "text/csv",
                   key="dx_csv", on_click="ignore")
with c2:
    if total <= EXCEL_MAX:
        st.download_button("Download Excel", lambda: excel_bytes(everything()), file_name=f"{fname}.xlsx", key="dx_xlsx",
                           on_click="ignore", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.caption(f"Excel download up to {EXCEL_MAX:,} rows; use CSV.")
st.caption("Read-only. To correct data, use Production Data → Edit (or export, fix in Excel and import again); "
           "the old version stays in Upload history.")
