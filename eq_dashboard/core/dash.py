"""Dashboard foundation: PUBLISHED data per site (cached), sidebar filters, combined targets, shared charts."""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

from auth.access import scope_filter
from core import metrics
from core.config import DEFAULT_CLIENT_STANDBY, UNMAPPED
from core.targets import METRICS
from core.ui import fmt_num, fmt_pct, require, sites_for
from db import models as m
from db import repo
from db.engine import session_scope

# colours follow the reference report: Type red, Model green, Unit yellow
COL_TYPE, COL_MODEL, COL_UNIT = "#E5484D", "#30A46C", "#F5B400"
COL_CAT = {"R": "#30A46C", "I": "#F5B400", "S": "#7F95C4", "D": "#E5484D"}
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


@st.cache_data(ttl=3600, show_spinner=False)
def _table(name: str, upload_id: int, site: str) -> pd.DataFrame:
    """Cached per table × upload × site (never per user). Access is filtered afterwards."""
    model, cols = TABLES[name]
    with session_scope() as s:
        return repo.frame(s, select(*[getattr(model, c) for c in cols])
                          .where(model.upload_id == upload_id, model.site == site))


@st.cache_data(ttl=3600, show_spinner=False)
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
    month: dt.date
    published: pd.DataFrame      # all PUBLISHED versions the user may see
    versions: pd.DataFrame       # versions of the selected sites × month
    ev: pd.DataFrame
    st: pd.DataFrame
    rit: pd.DataFrame
    coal: pd.DataFrame
    fuel: pd.DataFrame
    receipt: pd.DataFrame
    date_from: dt.date
    date_to: dt.date

    def dq(self) -> pd.DataFrame:
        parts = [_dq(int(r.upload_id), r.site) for r in self.versions.itertuples()]
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    def versions_for(self, scope: str) -> pd.DataFrame:
        """Versions for wider ranges: 'month' (selected), 'year' (selected year) or 'all'."""
        v = self.published[self.published["site"].isin(self.sites)]
        if scope == "month":
            return v[v["month"] == self.month]
        if scope == "year":
            return v[[mo.year == self.month.year for mo in v["month"]]]
        return v


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
            msg += " Upload a file in **Data → Upload data**, then wait for Site Manager approval."
        st.info(msg)
        st.stop()
    sb = st.sidebar
    sb.markdown("### Filters")
    avail = sorted(pub["site"].unique())
    sel = sb.multiselect("Site", avail, default=[x for x in avail if x != UNMAPPED] or avail, key="f_site")
    if not sel:
        st.warning("Select at least one site.")
        st.stop()
    months = sorted(pub[pub["site"].isin(sel)]["month"].unique(), reverse=True)
    month = sb.selectbox("Month", months, format_func=lambda d: pd.Timestamp(d).strftime("%B %Y"), key="f_month")
    versions = pub[(pub["site"].isin(sel)) & (pub["month"] == month)]

    ev = scope_filter(combine("events", versions), allowed)
    if ev.empty:
        st.info("No event data for this selection.")
        st.stop()
    dmin, dmax = ev["date"].min(), ev["date"].max()
    rng = sb.date_input("Dates", (dmin, dmax), min_value=dmin, max_value=dmax, key=f"f_date_{month}")
    d0, d1 = (rng if isinstance(rng, (tuple, list)) and len(rng) == 2 else (dmin, dmax))
    weeks = sb.multiselect("Week", sorted(ev["week"].unique()), key="f_week")
    shift = sb.segmented_control("Shift", ["DS", "NS"], selection_mode="multi", key="f_shift") or ["DS", "NS"]

    types = models = units = []
    if unit_filter:
        types = sb.multiselect("Type", sorted(ev["type"].dropna().unique()), key="f_type")
        e2 = ev[ev["type"].isin(types)] if types else ev
        models = sb.multiselect("Model", sorted(e2["model"].dropna().unique()), key="f_model")
        e3 = e2[e2["model"].isin(models)] if models else e2
        units = sb.multiselect("Unit ID", sorted(e3["unit_id"].unique()), key="f_unit")

    def by_date(df, col="date"):
        if df.empty:
            return df
        out = df[(df[col] >= d0) & (df[col] <= d1)]
        if weeks and "week" in out:
            out = out[out["week"].isin(weeks)]
        if "shift" in out and len(shift) < 2:
            out = out[out["shift"].isin(shift)]
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
    stp = scope_filter(combine("stoppages", versions), allowed)
    stp = by_unit(stp[(stp["start_date"] >= d0) & (stp["start_date"] <= d1)] if len(stp) else stp)
    rit = by_date(scope_filter(combine("ritase", versions), allowed))
    coal = by_date(scope_filter(combine("coal", versions), allowed))
    fuel = by_unit(by_date(scope_filter(combine("fuel", versions), allowed)))
    rec = scope_filter(combine("receipt", versions), allowed)
    rec = rec[(rec["date"] >= d0) & (rec["date"] <= d1)] if len(rec) else rec
    sb.caption(f"{', '.join(sel)} · {pd.Timestamp(month):%B %Y} · {d0:%d %b}–{d1:%d %b}")
    return Ctx(user, allowed, sel, month, pub, versions, ev_f, stp, rit, coal, fuel, rec, d0, d1)


# ------------------------------------------------------------------ targets & configuration
def targets(sites: list[str], month: dt.date, weights: pd.Series | None = None) -> dict[str, float | None]:
    """Combined target: one site → that site's target; several sites → hour-weighted average.
    If any site has no target the result is None (no target)."""
    with session_scope() as s:
        rows = repo.frame(s, select(m.Target.site, *[getattr(m.Target, c) for c in METRICS]).where(
            m.Target.site.in_(sites), m.Target.year == month.year, m.Target.month == month.month))
    out = {}
    for c in METRICS:
        vals = rows.set_index("site")[c].reindex(sites) if len(rows) else pd.Series(index=sites, dtype=float)
        if vals.isna().any():
            out[c] = None
            continue
        w = (weights.reindex(sites).fillna(0) if weights is not None else pd.Series(1.0, index=sites))
        out[c] = float(np.average(vals, weights=w)) if w.sum() > 0 else float(vals.mean())
    return out


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
    fmt = {"pct": fmt_pct, "h": lambda v: fmt_num(v, 1) + " h", "n": fmt_num, "n1": lambda v: fmt_num(v, 1),
           "n2": lambda v: fmt_num(v, 2)}[kind]
    if value is None or pd.isna(value):
        col.metric(label, "—", help=help)
        return
    if target is None or pd.isna(target):
        col.metric(label, fmt(value), "no target", delta_color="off", help=help)
        return
    diff = value - target
    dtxt = (f"{diff * 100:+.1f} pt" if kind == "pct" else f"{diff:+,.1f}") + f" vs target {fmt(target)}"
    col.metric(label, fmt(value), dtxt, delta_color="normal" if higher_better else "inverse", help=help)


def plot(fig: go.Figure, height: int = 360) -> None:
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=40, b=10), legend_title_text="",
                      font=dict(family=FONT), separators=".,")
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})


def ranking(df: pd.DataFrame, cat: str, val: str, title: str, color: str, pct: bool = True, top: int = 15,
            ascending: bool = False, height: int | None = None, digits: int = 0):
    d = df.sort_values(val, ascending=ascending).head(top).iloc[::-1]
    text = d[val].map(fmt_pct) if pct else d[val].map(lambda v: fmt_num(v, digits))
    fig = go.Figure(go.Bar(x=d[val], y=d[cat].astype(str), orientation="h", marker_color=color, text=text,
                           textposition="outside", cliponaxis=False))
    fig.update_layout(title=title, xaxis=dict(tickformat=".0%" if pct else ",", showgrid=True),
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
                      yaxis=dict(type="category", autorange="reversed"))
    plot(fig, max(280, 26 * len(b) + 90))


def pareto(df: pd.DataFrame, cat: str, val: str, title: str, color: str = "#E5484D", top: int = 12):
    d = df.groupby(cat, dropna=False)[val].sum().sort_values(ascending=False).head(top)
    cum = d.cumsum() / d.sum() if d.sum() else d
    fig = go.Figure()
    fig.add_bar(x=d.index.astype(str), y=d.values, marker_color=color, name=val)
    fig.add_scatter(x=d.index.astype(str), y=cum.values, yaxis="y2", mode="lines+markers", name="cumulative",
                    line=dict(color="#93A0B2"))
    fig.update_layout(title=title, yaxis2=dict(overlaying="y", side="right", tickformat=".0%", range=[0, 1.05]),
                      xaxis=dict(type="category"), showlegend=False)
    plot(fig, 380)


def weighted_target_hours(ev: pd.DataFrame) -> pd.Series:
    return metrics.time_buckets(ev, ["site"])["T"] if len(ev) else pd.Series(dtype=float)
