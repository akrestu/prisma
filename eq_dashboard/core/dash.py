"""Dashboard foundation: PUBLISHED data per site (cached), sidebar filters, combined targets, shared charts."""
from __future__ import annotations

import calendar
import datetime as dt
import html
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

from auth.access import scope_filter
from core import filters as F
from core import metrics
from core import theme as T
from core.clean import week_of
from core.config import DEFAULT_CLIENT_STANDBY, UNMAPPED, WIB
from core.targets import METRICS
from core.ui import fmt_num, fmt_pct, require, sites_for
from db import models as m
from db import repo
from db.engine import session_scope

# category bars are neutral; orange/blue are reserved for status (see core/theme.py)
COL_TYPE = COL_MODEL = COL_UNIT = T.NEUTRAL_BAR
COL_CAT = T.CAT
T.register_plotly()
CAT_LABEL = {"R": "Ready", "I": "Idle", "S": "Standby", "D": "Down"}
FONT = "IBM Plex Sans, sans-serif"
TABLES = {
    "events": (m.FactEvent, ["site", "date", "shift", "week", "seq", "unit_id", "type", "model", "operator",
                             "time_start", "hours", "hm_start", "hm_end", "status", "category", "reason_code",
                             "reason_text", "down_type"]),
    "stoppages": (m.FactStoppage, ["site", "unit_id", "type", "model", "start_date", "start_shift", "end_date",
                                   "hours", "sm_hours", "usm_hours", "main_reason", "hm_start"]),
    "ritase": (m.FactRitase, ["site", "site_hauler", "date", "hour_slot", "shift", "hauler", "hauler_model",
                              "muatan", "loader", "loader_model", "material", "material_group", "pit", "disposal",
                              "dist_v", "dist_h", "rit", "volume"]),
    "coal": (m.FactCoalTicket, ["site", "site_dt", "date", "shift", "ticket_id", "product", "seam", "dt_unit",
                                "loader", "ton", "time_in", "time_out"]),
    "fuel": (m.FactFuel, ["site", "date", "shift", "unit_id", "type", "model", "liters", "outlier"]),
    "receipt": (m.FactFuelReceipt, ["site", "date", "vendor", "unit", "dn_no", "liters"]),
}


# bounded caches: without max_entries memory grows with every month × site × table ever opened
@st.cache_data(ttl=3600, max_entries=240, show_spinner=False)
def _table(name: str, upload_id: int, site: str) -> pd.DataFrame:
    """Cached per table × upload × site (never per user). Access is filtered afterwards."""
    model, cols = TABLES[name]
    with session_scope() as s:
        return repo.frame(s, select(*[getattr(model, c) for c in cols])
                          .where(model.upload_id == upload_id, model.site == site))


@st.cache_data(ttl=3600, max_entries=60, show_spinner=False)
def _dq(upload_id: int, site: str) -> pd.DataFrame:
    with session_scope() as s:
        return repo.dq_findings(s, upload_id, site).assign(site=site)


def combine(name: str, versions: pd.DataFrame) -> pd.DataFrame:
    parts = [_table(name, int(r.upload_id), r.site) for r in versions.itertuples()]
    parts = [p for p in parts if len(p)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=TABLES[name][1])


@dataclass
class Ctx:
    user: object
    allowed: list[str]
    sites: list[str]
    month: dt.date               # month of the end of the range (used for "this year" scopes)
    published: pd.DataFrame      # all PUBLISHED versions the user may see
    versions: pd.DataFrame       # versions of the selected sites × months in the range
    ev: pd.DataFrame
    st: pd.DataFrame
    rit: pd.DataFrame
    coal: pd.DataFrame
    fuel: pd.DataFrame
    receipt: pd.DataFrame
    date_from: dt.date
    date_to: dt.date
    months: list[dt.date] = field(default_factory=list)
    anchor: dt.date | None = None          # last date with data
    last_complete: dt.date | None = None
    preset: str = F.DEFAULT_PRESET

    @property
    def single_month(self) -> bool:
        return len(self.months) == 1

    def dq(self) -> pd.DataFrame:
        parts = [_dq(int(r.upload_id), r.site) for r in self.versions.itertuples()]
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    def versions_for(self, scope: str) -> pd.DataFrame:
        """Versions for wider ranges: 'month' (selected range), 'year' (year of the range end) or 'all'."""
        v = self.published[self.published["site"].isin(self.sites)]
        if scope == "month":
            return v[v["month"].isin(self.months)]
        if scope == "year":
            return v[[mo.year == self.month.year for mo in v["month"]]]
        return v


def _seed_filters(user) -> None:
    """Once per session: restore filters from the URL, else the user's saved default. Afterwards a shadow copy
    (`_flt`) re-seeds widgets that Streamlit dropped while the user was on a page without the sidebar filters."""
    if "_flt" not in st.session_state:
        state = F.from_query(dict(st.query_params))
        if not state:
            with session_scope() as s:
                u = s.get(m.User, user.id)
                state = F.from_saved(u.default_filters if u else None)
        st.session_state["_flt"] = state
    for k, v in st.session_state["_flt"].items():
        if k not in st.session_state:
            st.session_state[k] = v


def _valid(key: str, options) -> None:
    """Drop stale values (from an old link or saved default) that are not options any more."""
    if key in st.session_state and isinstance(st.session_state[key], (list, tuple)):
        ok = set(options)
        st.session_state[key] = [x for x in st.session_state[key] if x in ok]


def _persist(state: dict) -> None:
    st.session_state["_flt"] = state
    q = F.to_query(state)
    if dict(st.query_params) != q:
        st.query_params.from_dict(q)


def context(page: str, unit_filter: bool = True) -> Ctx:
    """Page guard + sidebar filters + filtered PUBLISHED data."""
    user = require(page)
    allowed = [x for x in sites_for(user) if x != UNMAPPED or user.is_admin]
    with session_scope() as s:
        pub = repo.published_versions(s, allowed)
    if pub.empty:
        msg = "No published data for your sites yet."
        if user.role in ("admin", "site_manager"):
            msg += " Open **Data → Approval** to approve pending uploads."
        elif user.role == "data_officer":
            msg += " Import a workbook in **Data → Data_Prod**, then wait for Site Manager approval."
        st.info(msg)
        st.stop()
    _seed_filters(user)
    sb = st.sidebar
    sb.markdown("### Filters")
    avail = sorted(pub["site"].unique())
    _valid("f_site", avail)
    if not st.session_state.get("f_site"):
        st.session_state["f_site"] = [x for x in avail if x != UNMAPPED] or avail
    sel = sb.multiselect("Site", avail, key="f_site")
    if not sel:
        st.warning("Select at least one site.")
        st.stop()

    mine = pub[pub["site"].isin(sel)]
    months_avail = sorted(mine["month"].unique())
    latest = mine[mine["month"] == months_avail[-1]]
    ev_latest = scope_filter(combine("events", latest), allowed)
    anchor = ev_latest["date"].max() if len(ev_latest) else F.month_end(months_avail[-1])
    comp = metrics.complete_days(ev_latest) if len(ev_latest) else pd.Series(dtype=bool)
    last_complete = comp[comp].index.max() if comp.any() else None
    first = months_avail[0]

    if st.session_state.get("f_period") not in F.PRESETS:
        st.session_state["f_period"] = F.DEFAULT_PRESET
    preset = sb.selectbox("Period", list(F.PRESETS), format_func=F.PRESETS.get, key="f_period")
    custom = None
    if preset == "custom":
        rng = st.session_state.get("f_range")
        if not (isinstance(rng, (list, tuple)) and len(rng) == 2) or rng[0] < first or rng[1] > anchor:
            st.session_state["f_range"] = F.preset_range("mtd", anchor, first)
        picked = sb.date_input("From – to", min_value=first, max_value=anchor, key="f_range")
        custom = tuple(picked) if isinstance(picked, (list, tuple)) and len(picked) == 2 else None
    d0, d1 = F.preset_range(preset, anchor, first, last_complete, custom)
    avail_set = set(months_avail)
    months = [mo for mo in F.months_between(d0, d1) if mo in avail_set]
    versions = mine[mine["month"].isin(months)]

    ev = scope_filter(combine("events", versions), allowed)
    if ev.empty:
        st.info("No event data for this selection.")
        st.stop()
    week_opts = ["Week 1", "Week 2", "Week 3", "Week 4"]
    _valid("f_week", week_opts)
    weeks = sb.multiselect("Week of month", week_opts, key="f_week",
                           help="1–7, 8–14, 15–21, 22–end of each month in the period")
    _valid("f_shift", ["DS", "NS"])
    shift = sb.segmented_control("Shift", ["DS", "NS"], selection_mode="multi", key="f_shift") or ["DS", "NS"]

    types = models = units = []
    if unit_filter:
        _valid("f_type", ev["type"].dropna().unique())
        types = sb.multiselect("Type", sorted(ev["type"].dropna().unique()), key="f_type")
        e2 = ev[ev["type"].isin(types)] if types else ev
        _valid("f_model", e2["model"].dropna().unique())
        models = sb.multiselect("Model", sorted(e2["model"].dropna().unique()), key="f_model")
        e3 = e2[e2["model"].isin(models)] if models else e2
        _valid("f_unit", e3["unit_id"].unique())
        units = sb.multiselect("Unit ID", sorted(e3["unit_id"].unique()), key="f_unit")

    def by_date(df, col="date", shift_col="shift"):
        """Date range, week and shift filters for any table. Tables without a week column (ritase, coal, fuel,
        receipts, stoppages) get the week from their date, so Week filters every figure on the page, not only PA."""
        if df.empty:
            return df
        out = df[(df[col] >= d0) & (df[col] <= d1)]
        if weeks:
            wk = out["week"] if "week" in out else week_of(pd.to_datetime(out[col]).dt.day).set_axis(out.index)
            out = out[wk.isin(weeks)]
        if shift_col in out and len(shift) < 2:
            out = out[out[shift_col].isin(shift)]
        return out

    def by_unit(df, col="unit_id"):
        if df.empty:
            return df
        if types and "type" in df:
            df = df[df["type"].isin(types)]
        if models and "model" in df:
            df = df[df["model"].isin(models)]
        if units:
            df = df[df[col].isin(units)]
        return df

    ev_f = by_unit(by_date(ev))
    # a stoppage belongs to the day and shift it started in, so MTBS/MTTR follow the same filters as the hours
    stp = by_unit(by_date(scope_filter(combine("stoppages", versions), allowed), "start_date", "start_shift"))
    rit = by_date(scope_filter(combine("ritase", versions), allowed))
    coal = by_date(scope_filter(combine("coal", versions), allowed))
    fuel = by_unit(by_date(scope_filter(combine("fuel", versions), allowed)))
    rec = by_date(scope_filter(combine("receipt", versions), allowed), shift_col="-")  # deliveries: no shift split

    state = {k: st.session_state.get(k) for k in (*F.FIELDS, "f_range")}
    _persist(state)
    _filter_actions(user, state)
    c = Ctx(user, allowed, sel, F.month_start(d1), pub, versions, ev_f, stp, rit, coal, fuel, rec, d0, d1,
            months=months, anchor=anchor, last_complete=last_complete, preset=preset)
    coverage(c)
    return c


def _filter_actions(user, state: dict) -> None:
    a, b = st.sidebar.columns(2)
    if a.button("Save as default", key="flt_save", help="Open the dashboard with these filters every time you sign in"):
        with session_scope() as s:
            s.get(m.User, user.id).default_filters = F.to_saved(state)
        st.toast("Saved as your default filters")
    if b.button("Reset", key="flt_reset", help="Back to all sites, month to date"):
        for k in (*F.FIELDS, "f_range"):
            st.session_state.pop(k, None)
        st.session_state["_flt"] = {}
        st.query_params.clear()
        st.rerun()


def coverage(c: Ctx) -> None:
    """One muted line above the page title: which sites and dates, how fresh, when approved."""
    approved = pd.to_datetime(c.versions["reviewed_at"]).max() if len(c.versions) else None
    parts = [html.escape(", ".join(c.sites)), f"<b>{F.range_label(c.date_from, c.date_to)}</b>",
             F.PRESETS[c.preset].lower()]
    if c.anchor:
        fresh = f"data up to {c.anchor.day} {c.anchor:%b}"
        if c.last_complete and c.last_complete != c.anchor:
            fresh += f" (last complete day {c.last_complete.day} {c.last_complete:%b})"
        parts.append(fresh)
    if approved is not None and pd.notna(approved):
        parts.append(f"approved {approved.tz_convert(WIB):%d %b %H:%M}")
    st.markdown(f'<div style="color:{T.MUTED};font-size:.85rem;margin:0 0 -.4rem">{" · ".join(parts)}</div>',
                unsafe_allow_html=True)


# ------------------------------------------------------------------ targets & configuration
def targets_for(c: Ctx) -> dict[str, float | None]:
    """Target for the selected sites and period. Each site × month is weighted by its hours in the filtered data,
    so a range across months or sites gets one fair target. If any site-month with hours has no target → None."""
    if c.ev.empty:
        return dict.fromkeys(METRICS)
    w = (c.ev.assign(month=pd.to_datetime(c.ev["date"]).dt.to_period("M").dt.to_timestamp().dt.date)
         .pipe(lambda e: metrics.time_buckets(e, ["site", "month"]))["T"])
    w = w[w > 0]
    with session_scope() as s:
        rows = repo.frame(s, select(m.Target.site, m.Target.year, m.Target.month,
                                    *[getattr(m.Target, x) for x in METRICS]).where(m.Target.site.in_(c.sites)))
    if rows.empty:
        return dict.fromkeys(METRICS)
    rows["mo"] = [dt.date(int(y), int(mo), 1) for y, mo in zip(rows["year"], rows["month"], strict=True)]
    tab = rows.set_index(["site", "mo"])
    out = {}
    for x in METRICS:
        vals = tab[x].reindex(w.index)
        out[x] = None if vals.isna().any() or w.sum() == 0 else float(np.average(vals, weights=w))
    return out


def plan_range(sites: list[str], d0: dt.date, d1: dt.date) -> pd.DataFrame:
    """Daily OB / coal plan over any date range (months joined; a monthly plan is spread over its days)."""
    parts = [plan_daily(tuple(sites), mo) for mo in F.months_between(d0, d1)]
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["date", "ob_plan", "coal_plan"])
    return out[(out["date"] >= d0) & (out["date"] <= d1)].reset_index(drop=True)


@st.cache_data(ttl=600, show_spinner=False)
def pm_intervals() -> pd.DataFrame:
    with session_scope() as s:
        return repo.frame(s, select(m.PMInterval.model, m.PMInterval.interval_hm, m.PMInterval.tolerance_pct))


@st.cache_data(ttl=600, show_spinner=False)
def client_standby_codes() -> set[int]:
    with session_scope() as s:
        rows = list(s.execute(select(m.StandbyGroup.reason_code, m.StandbyGroup.grp)))
    return {c for c, g in rows if g == "client"} if rows else set(DEFAULT_CLIENT_STANDBY)


@st.cache_data(ttl=600, show_spinner=False)
def plan_daily(sites: tuple[str, ...], month: dt.date) -> pd.DataFrame:
    """Daily plan per date (all selected sites). A monthly plan is spread evenly over calendar days."""
    days = calendar.monthrange(month.year, month.month)[1]
    dates = [dt.date(month.year, month.month, d) for d in range(1, days + 1)]
    with session_scope() as s:
        rows = repo.frame(s, select(m.PlanProduction.site, m.PlanProduction.date, m.PlanProduction.ob_bcm,
                                    m.PlanProduction.coal_ton)
                          .where(m.PlanProduction.site.in_(sites), m.PlanProduction.year == month.year,
                                 m.PlanProduction.month == month.month))
    out = pd.DataFrame({"date": dates, "ob_plan": 0.0, "coal_plan": 0.0})
    if rows.empty:
        return out.assign(ob_plan=np.nan, coal_plan=np.nan)
    for _site, g in rows.groupby("site"):
        daily = g[g["date"].notna()].set_index("date")
        monthly = g[g["date"].isna()]
        for col, src in (("ob_plan", "ob_bcm"), ("coal_plan", "coal_ton")):
            v = out["date"].map(daily[src]) if len(daily) else pd.Series(np.nan, index=out.index)
            if len(monthly) and monthly[src].notna().any():
                v = v.fillna(monthly[src].sum() / days)
            out[col] = out[col] + v.fillna(0)
    return out


# ------------------------------------------------------------------ display
def kpi(col, label: str, value, target=None, kind: str = "pct", higher_better: bool = True, help: str | None = None):
    """KPI card: actual, target, difference (coloured). No target → 'no target'."""
    fmt = {"pct": fmt_pct, "h": lambda v: fmt_num(v, 1) + " hrs", "n": fmt_num, "n1": lambda v: fmt_num(v, 1),
           "n2": lambda v: fmt_num(v, 2)}[kind]
    if value is None or pd.isna(value):
        col.metric(label, "—", help=help)
        return
    if target is None or pd.isna(target):
        col.metric(label, fmt(value), "no target", delta_color="gray", delta_arrow="off", help=help)
        return
    diff = value - target
    dtxt = (f"{diff * 100:+.1f}%" if kind == "pct" else f"{diff:+,.1f}") + f" vs target {fmt(target)}"
    miss = T.miss_level(value, target, higher_better) == 2
    col.metric(label, fmt(value), dtxt, delta_color="orange" if miss else "gray", help=help)


def plot(fig: go.Figure, height: int = 360, bottom: int = 10) -> None:
    named = [tr for tr in fig.data if getattr(tr, "showlegend", None) is not False and getattr(tr, "name", None)]
    if len(named) > 1 and fig.layout.showlegend is not False and fig.layout.legend.y is None:
        # a legend at the top collides with the chart title: put it under the x axis instead
        fig.update_layout(legend=dict(orientation="h", traceorder="normal", x=0, xanchor="left",
                                      yref="container", y=0, yanchor="bottom"))
        bottom, height = max(bottom, 56), height + 30
    fig.update_layout(template="haulroad", height=height, margin=dict(l=10, r=10, t=48, b=bottom), legend_title_text="")
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})


def ranking(df: pd.DataFrame, cat: str, val: str, title: str, color: str, pct: bool = True, top: int = 15,
            ascending: bool = False, height: int | None = None, digits: int = 0):
    d = df.sort_values(val, ascending=ascending).head(top).iloc[::-1]
    text = d[val].map(fmt_pct) if pct else d[val].map(lambda v: fmt_num(v, digits))
    fig = go.Figure(go.Bar(x=d[val], y=d[cat].astype(str), orientation="h", marker_color=color, text=text,
                           textposition="outside", cliponaxis=False))
    top = float(d[val].max()) if len(d) and pd.notna(d[val].max()) else 0.0
    upper = max(top, 1.0 if pct else 0.0) * 1.18 or 1.0
    fig.update_layout(title=title, xaxis=dict(tickformat=".0%" if pct else ",", showgrid=True, range=[0, upper]),
                      yaxis=dict(type="category"))
    plot(fig, height or max(260, 26 * len(d) + 80))


def stacked_dist(ev: pd.DataFrame, by: str, title: str, top: int = 20):
    b = metrics.time_buckets(ev, [by])
    b = b[b["T"] > 0].sort_values("T", ascending=False).head(top)
    fig = go.Figure()
    for c in "RISD":
        fig.add_bar(y=b.index.astype(str), x=b[c] / b["T"], name=CAT_LABEL[c], orientation="h",
                    marker_color=COL_CAT[c], text=(b[c] / b["T"]).map(lambda v: f"{v:.0%}" if v >= .06 else ""),
                    textposition="inside")
    fig.update_layout(barmode="stack", title=title, xaxis=dict(tickformat=".0%", range=[0, 1]),
                      yaxis=dict(type="category", autorange="reversed"),
                      legend=dict(orientation="h", traceorder="normal", x=0, xanchor="left",
                                  yref="container", y=0, yanchor="bottom"))  # below the axis, clear of the title
    plot(fig, max(300, 26 * len(b) + 130), bottom=56)


def pareto(df: pd.DataFrame, cat: str, val: str, title: str, color: str = T.DOWN, top: int = 12):
    d = df.groupby(cat, dropna=False)[val].sum().sort_values(ascending=False).head(top)
    cum = d.cumsum() / d.sum() if d.sum() else d
    fig = go.Figure()
    fig.add_bar(x=d.index.astype(str), y=d.values, marker_color=color, name=val)
    fig.add_scatter(x=d.index.astype(str), y=cum.values, yaxis="y2", mode="lines+markers", name="cumulative",
                    line=dict(color=T.ACCENT))
    fig.update_layout(title=title, yaxis2=dict(overlaying="y", side="right", tickformat=".0%", range=[0, 1.05]),
                      xaxis=dict(type="category"), showlegend=False)
    plot(fig, 380)


def summary(*parts: str) -> None:
    """One plain sentence under the page title that says what matters most."""
    text = ". ".join(p.rstrip(".")[:1].upper() + p.rstrip(".")[1:] for p in parts if p)
    if text:
        text = html.escape(text)  # parts contain names read from uploaded workbooks (reasons, units, sites)
        st.markdown(f'<div style="border-left:3px solid {T.ACCENT};padding:2px 0 2px 12px;margin:-4px 0 14px;'
                    f'font-size:1.02rem;color:{T.TEXT}">{text}.</div>', unsafe_allow_html=True)


def gap_text(name: str, value, target, unit: str = "%", higher_better: bool = True) -> str:
    """'UoA 47.3%, 12.7% below target' / '' when no target."""
    if value is None or pd.isna(value):
        return ""
    val = f"{value * 100:.1f}%" if unit == "%" else f"{value:,.1f} {unit}"
    if target is None:
        return f"{name} {val} (no target set)"
    diff = value - target
    size = f"{abs(diff) * 100:.1f}%" if unit == "%" else f"{abs(diff):,.1f} {unit}"
    side = ("above" if diff >= 0 else "below")
    return f"{name} {val}, {size} {side} target"

