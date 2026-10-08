"""Dashboard foundation: PUBLISHED data per site (cached), filter bar, combined targets, shared charts."""
from __future__ import annotations

import calendar
import datetime as dt
import html
from dataclasses import dataclass, field
from urllib.parse import urlencode

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
from core.config import DEFAULT_CLIENT_STANDBY, UNMAPPED, WIB, today_wib
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


@st.cache_data(ttl=600, max_entries=60, show_spinner=False)
def _hourly_ritase(sites: tuple, d0: dt.date, d1: dt.date, stamp: str) -> pd.DataFrame:
    """Hourly Production ritase; `stamp` changes on every shift save, so new input shows at once."""
    with session_scope() as s:
        return repo.hourly_ritase(s, list(sites), d0, d1)


def ritase(versions: pd.DataFrame, allowed: list[str]) -> pd.DataFrame:
    """Official ritase of the versions' sites and months: Production Data before the cutover date, Hourly
    Production from it on (core.hourly.official_ritase)."""
    from core import hourly as H
    imported = scope_filter(combine("ritase", versions), allowed)
    if versions.empty:
        return imported
    sites = sorted(set(versions["site"]) & set(allowed))
    with session_scope() as s:
        cut = repo.hourly_cutover(s)
        stamp = repo.hourly_stamp(s, sites) if cut else ""
    if cut is None:
        return imported
    d0, d1 = max(min(versions["month"]), cut), F.month_end(max(versions["month"]))
    hourly = _hourly_ritase(tuple(sites), d0, d1, stamp) if d0 <= d1 else None
    return H.official_ritase(imported, hourly, cut)


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
    compare: bool = False
    prev: object = None                    # Loaded data of the previous period (compare on and data exists)
    prev_range: tuple | None = None

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
    """Once per session: restore filters from the URL (a shared link), else the user's last used filters. Afterwards
    a shadow copy (`_flt`) re-seeds widgets that Streamlit dropped while the user was on a page without filters."""
    if "_flt" not in st.session_state:
        state = F.from_query(dict(st.query_params))
        with session_scope() as s:
            u = s.get(m.User, user.id)
            saved = u.default_filters if u else None
        if not state:
            state = F.from_saved(saved)
        st.session_state["_flt"] = state
        st.session_state["_flt_saved"] = saved
    for k, v in st.session_state["_flt"].items():
        if k not in st.session_state:
            st.session_state[k] = v


def _valid(key: str, options) -> None:
    """Drop stale values (from an old link or saved filters) that are not options any more."""
    if key in st.session_state and isinstance(st.session_state[key], (list, tuple)):
        ok = set(options)
        st.session_state[key] = [x for x in st.session_state[key] if x in ok]


def _persist(user, state: dict) -> None:
    """Keep the filters in the URL (refresh, share) and in the user's row (next sign-in, other devices).
    The database is written only when the filters changed, not on every rerun."""
    st.session_state["_flt"] = state
    q = F.to_query(state)
    if dict(st.query_params) != q:
        st.query_params.from_dict(q)
    saved = F.to_saved(state)
    if saved != st.session_state.get("_flt_saved"):
        with session_scope() as s:
            u = s.get(m.User, user.id)
            if u is not None:
                u.default_filters = saved
        st.session_state["_flt_saved"] = saved


@dataclass
class Loaded:
    versions: pd.DataFrame
    months: list[dt.date]
    ev: pd.DataFrame
    st: pd.DataFrame
    rit: pd.DataFrame
    coal: pd.DataFrame
    fuel: pd.DataFrame
    receipt: pd.DataFrame


def context(page: str, unit_filter: bool = True, title: str | None = None) -> Ctx:
    """Page guard + filter bar + filtered PUBLISHED data. `title` is shown when the page stops early (no data),
    so an empty page still says where the user is; otherwise the page shows its own title below the filters."""

    def halt(show, msg: str) -> None:
        if title:
            st.title(title)
        show(msg)
        st.stop()

    user = require(page)
    allowed = [x for x in sites_for(user) if x != UNMAPPED or user.is_admin]
    with session_scope() as s:
        pub = repo.published_versions(s, allowed)
    if pub.empty:
        msg = "No published data for your sites yet."
        if user.role in ("admin", "site_manager"):
            msg += " Open **Approval** to approve pending uploads."
        elif user.role == "data_officer":
            msg += " Import a workbook in **Input & upload → Upload Production Data**, then wait for Site Manager approval."
        halt(st.info, msg)
    _seed_filters(user)

    bar = st.container(border=True)
    r = bar.columns([2.2, 1.6, 1.9, 1.2, 0.9], vertical_alignment="bottom")   # wide enough for "Compare"
    avail = sorted(pub["site"].unique())
    _valid("f_site", avail)
    if not st.session_state.get("f_site"):
        st.session_state["f_site"] = [x for x in avail if x != UNMAPPED] or avail
    sel = r[0].multiselect("Site", avail, key="f_site")
    if not sel:
        halt(st.warning, "Select at least one site.")

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
    preset = r[1].selectbox("Period", list(F.PRESETS), format_func=F.PRESETS.get, key="f_period",
                            help="Today / yesterday / weeks follow today's date. The others count back from "
                                 "the last date that has published data.")
    custom = None
    if preset == "custom":
        rng = st.session_state.get("f_range")
        if not (isinstance(rng, (list, tuple)) and len(rng) == 2) or rng[0] < first or rng[1] > anchor:
            st.session_state["f_range"] = F.preset_range("mtd", anchor, first)
        picked = r[2].date_input("From – to", min_value=first, max_value=anchor, key="f_range", format="DD/MM/YYYY")
        custom = tuple(picked) if isinstance(picked, (list, tuple)) and len(picked) == 2 else None
    d0, d1 = F.preset_range(preset, anchor, first, last_complete, custom, today=today_wib())
    moved = None
    if preset in F.CALENDAR and d0 > anchor:
        # Production Data lags a few days: show the same span ending on the latest data instead of an empty page
        span, end = d1 - d0, (last_complete or anchor) if preset in ("today", "yesterday") else anchor
        moved = (d0, d1)
        d0, d1 = max(end - span, first), end
    elif preset == "last_month" and d0 == d1 == anchor:
        # preset_range falls back to the latest day when last month has no data: say so instead of a silent swap
        prev_end = F.month_start(anchor) - dt.timedelta(days=1)
        moved = (F.month_start(prev_end), prev_end)
    if preset != "custom":
        # a keyed widget keeps its first value: set it every run so the label follows the dates shown
        st.session_state["f_range_label"] = F.range_label(d0, d1)
        r[2].text_input("From – to", disabled=True, key="f_range_label")
    cmp_on = r[3].toggle("Compare", key="f_cmp", help="Show the change against the previous period on the KPI cards")

    more = r[4].popover("More", icon=":material/tune:", width="stretch")
    week_opts = ["Week 1", "Week 2", "Week 3", "Week 4"]
    _valid("f_week", week_opts)
    weeks = more.multiselect("Week of month", week_opts, key="f_week",
                             help="1–7, 8–14, 15–21, 22–end of each month in the period")
    _valid("f_shift", ["DS", "NS"])
    shift = more.segmented_control("Shift", ["DS", "NS"], selection_mode="multi", key="f_shift") or ["DS", "NS"]
    extra = [f"Week {', '.join(w[-1] for w in weeks)}" if weeks else "", shift[0] if len(shift) == 1 else ""]

    if moved:
        bar.caption(f":material/info: No published data for **{F.PRESETS[preset].lower()}** "
                    f"({F.range_label(*moved)}) yet: showing the latest data, **{F.range_label(d0, d1)}**.")
    if d0 > anchor or d1 < first:
        _actions(bar, user)
        halt(st.info, f"No published data for **{F.PRESETS[preset].lower()}** ({F.range_label(d0, d1)}) yet. "
             f"Data runs from {first:%d %b %Y} to {anchor:%d %b %Y}; pick **Last complete day** or **Month to "
             "date** to see the latest.")
    d0, d1 = max(d0, first), min(d1, anchor)

    def load(a: dt.date, b: dt.date) -> Loaded | None:
        avail_set = set(months_avail)
        months = [mo for mo in F.months_between(a, b) if mo in avail_set]
        versions = mine[mine["month"].isin(months)]
        ev = scope_filter(combine("events", versions), allowed)
        if ev.empty:
            return None

        def by_date(df, col="date", shift_col="shift"):
            """Date range, week and shift filters for any table. Tables without a week column (ritase, coal, fuel,
            receipts, stoppages) get the week from their date, so Week filters every figure on the page."""
            if df.empty:
                return df
            out = df[(df[col] >= a) & (df[col] <= b)]
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

        # a stoppage belongs to the day and shift it started in, so MTBS/MTTR follow the same filters as the hours
        return Loaded(
            versions, months, by_unit(by_date(ev)),
            by_unit(by_date(scope_filter(combine("stoppages", versions), allowed), "start_date", "start_shift")),
            by_date(ritase(versions, allowed)),
            by_date(scope_filter(combine("coal", versions), allowed)),
            by_unit(by_date(scope_filter(combine("fuel", versions), allowed))),
            by_date(scope_filter(combine("receipt", versions), allowed), shift_col="-"))  # deliveries: no shift

    types = models = units = []
    if unit_filter:
        ev_all = scope_filter(combine("events", mine[mine["month"].isin(F.months_between(d0, d1))]), allowed)
        ev_all = ev_all[(ev_all["date"] >= d0) & (ev_all["date"] <= d1)] if len(ev_all) else ev_all
        _valid("f_type", ev_all["type"].dropna().unique() if len(ev_all) else [])
        types = more.multiselect("Type", sorted(ev_all["type"].dropna().unique()) if len(ev_all) else [], key="f_type")
        e2 = ev_all[ev_all["type"].isin(types)] if types else ev_all
        _valid("f_model", e2["model"].dropna().unique() if len(e2) else [])
        models = more.multiselect("Model", sorted(e2["model"].dropna().unique()) if len(e2) else [], key="f_model")
        e3 = e2[e2["model"].isin(models)] if models else e2
        _valid("f_unit", e3["unit_id"].unique() if len(e3) else [])
        units = more.multiselect("Unit ID", sorted(e3["unit_id"].unique()) if len(e3) else [], key="f_unit")
        extra += [f"{len(types)} type(s)" if types else "", f"{len(models)} model(s)" if models else "",
                  f"{len(units)} unit(s)" if units else ""]
    _actions(bar, user, [x for x in extra if x])

    cur = load(d0, d1)
    if cur is None:
        halt(st.info, "No event data for this selection.")
    prev_rng = prev = None
    if cmp_on:
        prev_rng = F.previous_range(preset, d0, d1)
        prev = load(*prev_rng) if prev_rng[1] >= first else None

    state = {k: st.session_state.get(k) for k in (*F.FIELDS, "f_range")}
    _persist(user, state)
    c = Ctx(user, allowed, sel, F.month_start(d1), pub, cur.versions, cur.ev, cur.st, cur.rit, cur.coal, cur.fuel,
            cur.receipt, d0, d1, months=cur.months, anchor=anchor, last_complete=last_complete, preset=preset,
            compare=cmp_on, prev=prev, prev_range=prev_rng)
    coverage(c)
    return c


def _actions(bar, user, active: list[str] | None = None) -> None:
    """Under the filter bar: which extra filters are on, a shareable link, reset."""
    a, b, c = bar.columns([6, 1, 1], vertical_alignment="center")
    a.caption(("Also filtered by: " + " · ".join(active)) if active else
              "Filters are remembered for your account and kept in the page link.")
    with b.popover("Share", icon=":material/link:", width="stretch"):
        st.caption("Anyone with access to these sites sees the same view with this link.")
        base = (st.context.url or "").split("?")[0]
        q = urlencode(F.to_query({k: st.session_state.get(k) for k in (*F.FIELDS, "f_range")}), safe=",")
        st.code(f"{base}?{q}" if q else base, language=None, wrap_lines=True)
    if c.button("Reset", key="flt_reset", icon=":material/restart_alt:", width="stretch",
                help="Back to all sites, month to date"):
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
    if c.compare and c.prev_range:
        parts.append(f"compared with {F.range_label(*c.prev_range)}" if c.prev is not None
                     else f"no published data to compare for {F.range_label(*c.prev_range)}")
    st.markdown(f'<div style="color:var(--pr-muted);font-size:.85rem;margin:0 0 -.4rem">{" · ".join(parts)}</div>',
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
def kpi(col, label: str, value, target=None, kind: str = "pct", higher_better: bool = True, help: str | None = None,
        prev=None):
    """KPI card: actual, target, difference (coloured). No target → 'no target'. With `prev` (compare on), a second
    line gives the change against the previous period."""
    fmt = {"pct": fmt_pct, "h": lambda v: fmt_num(v, 1) + " hrs", "n": fmt_num, "n1": lambda v: fmt_num(v, 1),
           "n2": lambda v: fmt_num(v, 2)}[kind]
    if value is None or pd.isna(value):
        col.metric(label, "—", help=help)
    elif target is None or pd.isna(target):
        col.metric(label, fmt(value), "no target", delta_color="gray", delta_arrow="off", help=help)
    else:
        diff = value - target
        dtxt = (f"{diff * 100:+.1f}%" if kind == "pct" else f"{diff:+,.1f}") + f" vs target {fmt(target)}"
        miss = T.miss_level(value, target, higher_better) == 2
        col.metric(label, fmt(value), dtxt, delta_color="orange" if miss else "gray", help=help)
    if prev is not None and not pd.isna(prev) and value is not None and not pd.isna(value):
        col.caption(change_text(value, prev, kind, higher_better))


def headline(d) -> dict:
    """Headline figures of a Ctx or Loaded (PA, UoA, MA, EU, MTBS, MTTR, MTBF, SchedDown, OB, coal, fuel).
    None → {} so `prev.get(x)` stays None when there is nothing to compare with."""
    if d is None or d.ev.empty:
        return {}
    k = metrics.kpis(d.ev).iloc[0]
    r = metrics.reliability(d.ev, d.st).iloc[0]
    return {**{x: k[x] for x in ("PA", "UoA", "MA", "EU")}, **{x: r[x] for x in ("MTBS", "MTTR", "MTBF", "SchedDown")},
            "OB": d.rit.loc[d.rit["material_group"] == "OB", "volume"].sum() if len(d.rit) else 0,
            "coal": d.coal["ton"].sum() if len(d.coal) else 0,
            "fuel": d.fuel["liters"].sum() if len(d.fuel) else 0}


def change_text(value, prev, kind: str = "n", higher_better: bool = True) -> str:
    """'▲ +2.1 pts vs previous (84.0%)' / '▼ −12% vs previous (1,203)'; worse changes are marked in orange."""
    diff = value - prev
    if kind == "pct":
        txt = f"{diff * 100:+.1f} pts"
    elif prev:
        txt = f"{diff / abs(prev):+.0%}"
    else:
        txt = f"{diff:+,.1f}"
    arrow = "▲" if diff > 0 else "▼" if diff < 0 else "="
    was = fmt_pct(prev) if kind == "pct" else fmt_num(prev, 1 if kind in ("h", "n1") else 0)
    worse = (diff < 0) if higher_better else (diff > 0)
    s = f"{arrow} {txt} vs previous ({was})"
    return f":orange[{s}]" if worse and diff != 0 else s


def plot(fig: go.Figure, height: int = 360, bottom: int = 10) -> None:
    named = [tr for tr in fig.data if getattr(tr, "showlegend", None) is not False and getattr(tr, "name", None)]
    if len(named) > 1 and fig.layout.showlegend is not False and fig.layout.legend.y is None:
        # a legend at the top collides with the chart title: put it under the x axis instead
        fig.update_layout(legend=dict(orientation="h", traceorder="normal", x=0, xanchor="left",
                                      yref="container", y=0, yanchor="bottom"))
        bottom, height = max(bottom, 56), height + 30
    fig.update_layout(template="streamlit+haulroad", height=height, margin=dict(l=10, r=10, t=48, b=bottom), legend_title_text="")
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
                    f'font-size:1.02rem;color:var(--pr-text)">{text}.</div>', unsafe_allow_html=True)


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

