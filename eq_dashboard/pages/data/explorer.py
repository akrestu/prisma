"""Data explorer: read-only raw rows per table, filtered by version, site, dates and text; CSV / Excel download."""
import pandas as pd
import streamlit as st

from auth.access import ADMIN, DATA_OFFICER, SITE_MANAGER, can_review
from core import dash
from core import ingest as ing
from core.ui import excel_download, fmt_num, require, sites_for
from db import repo
from db.engine import session_scope

EXCEL_MAX = 100_000  # bigger results download as CSV only (Excel gets slow and heavy)
PAGE_ROWS = 2_000    # rows sent to the browser per page

user = require("data_explorer")
sites = sites_for(user)
st.title("Data explorer")

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

@st.cache_data(ttl=600, max_entries=20, show_spinner=False)
def _rows(table: str, versions: tuple[tuple[int, str], ...]) -> pd.DataFrame:
    """Cached per table × versions (never per user: `versions` is already limited to what this user may see),
    so typing in the search boxes does not query the database again."""
    with session_scope() as s:
        return repo.explorer_rows(s, table, list(versions))


with st.spinner(f"Loading {table.lower()}…"):
    df = _rows(table, tuple(sorted(versions)))

date_col = repo.EXPLORER_TABLES[table][1]
f1, f2, f3 = st.columns([1.3, 1, 1.7])
if date_col and len(df) and df[date_col].notna().any():
    dmin, dmax = pd.to_datetime(df[date_col]).min().date(), pd.to_datetime(df[date_col]).max().date()
    rng = f1.date_input("Dates", (dmin, dmax), min_value=dmin, max_value=dmax, key=f"dx_dates_{table}_{label}")
    if isinstance(rng, (tuple, list)) and len(rng) == 2:
        d = pd.to_datetime(df[date_col]).dt.date
        df = df[(d >= rng[0]) & (d <= rng[1]) | d.isna()]
unit_cols = [c for c in ("unit_id", "hauler", "loader", "dt_unit", "unit") if c in df.columns]
units = f2.text_input("Unit ID", key="dx_unit", placeholder="e.g. WEX019").strip().upper()
if units and unit_cols:
    hit = pd.Series(False, index=df.index)
    for c in unit_cols:
        hit |= df[c].astype(str).str.upper().str.contains(units, regex=False, na=False)
    df = df[hit]
text = f3.text_input("Search all columns", key="dx_text", placeholder="reason, material, ticket, seam…").strip()
if text:
    txt_cols = [c for c in df.columns if df[c].dtype == object]
    hit = pd.Series(False, index=df.index)
    for c in txt_cols:
        hit |= df[c].astype(str).str.contains(text, case=False, regex=False, na=False)
    df = df[hit]

dash.summary(f"{fmt_num(len(df))} rows of {table.lower()}", label,
             f"{len({s_ for _, s_ in versions})} site(s)")
if len(df) >= 200_000:
    st.warning("Showing the first 200,000 rows. Narrow the months or sites to see everything.")

# only one page of rows goes to the browser; downloads always contain every filtered row
pages = max(1, -(-len(df) // PAGE_ROWS))
page = 1
if pages > 1:
    p1, p2 = st.columns([1, 5])
    page = int(p1.number_input("Page", 1, pages, 1, key=f"dx_page_{table}_{label}"))
    p2.caption(f"Rows {(page - 1) * PAGE_ROWS + 1:,}–{min(page * PAGE_ROWS, len(df)):,} of {len(df):,}")
st.dataframe(df.iloc[(page - 1) * PAGE_ROWS: page * PAGE_ROWS], hide_index=True, width="stretch", height=560)

fname = table.split(" (")[0].lower().replace(" ", "_")
c1, c2, _ = st.columns([1, 1, 4])
c1.download_button("Download CSV", lambda: df.to_csv(index=False).encode("utf-8-sig"), f"{fname}.csv", "text/csv",
                   key="dx_csv", on_click="ignore")
with c2:
    if len(df) <= EXCEL_MAX:
        excel_download(df, f"{fname}.xlsx", key="dx_xlsx")
    else:
        st.caption(f"Excel download up to {EXCEL_MAX:,} rows; use CSV.")
st.caption("Read-only. To correct data, export it from Data_Prod, fix it in Excel and import it again; "
           "the old version stays in Upload history.")
