"""Loader & hauler productivity for OB (BCM/h) and CG (t/h) with haul distance, hourly → yearly, against the
Production Data default productivity per model (internal or client)."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from auth.access import scope_filter
from core import dash
from core import prod_target as PT
from core import theme as T
from core.periods import (
    PERIOD_LABEL,
    PERIODS,
    UNIT,
    bucket,
    bucket_order,
    fleet_summary,
    pretty,
    productivity,
    split_hourly,
    with_week,
)
from core.ui import excel_download, fmt_num
from db import repo
from db.engine import session_scope

c = dash.context("loader_fleet", unit_filter=False)
st.title("Loader & hauler productivity")

with session_scope() as s:
    ld_def, hl_def = repo.model_targets(s), repo.hauler_targets(s)
    site_basis = repo.site_basis(s, c.sites[0])
a, b, bb = st.columns([3, 2, 2])
basis = bb.segmented_control("Target", list(PT.BASES), default=site_basis, key="prod_basis",
                             format_func=lambda x: "Internal (WBK)" if x == "internal" else "Client (BAU)",
                             help="Production Data default productivity per model (Settings → Production targets)"
                             ) or site_basis
period = a.segmented_control("Granularity", PERIODS, default="daily", format_func=PERIOD_LABEL.get,
                             key="prod_period") or "daily"
group = b.segmented_control("Material", ["OB", "CG"], default="OB", key="prod_group",
                            format_func=lambda g: "OB (BCM)" if g == "OB" else "Coal getting (t)") or "OB"
unit = UNIT[group]
scope = {"hourly": "month", "daily": "month", "weekly": "month", "monthly": "year", "yearly": "all"}[period]
st.caption({
    "hourly": "Hourly profile over the selected dates (by production hour 06-07 … 05-06).",
    "daily": "Per day within the selected dates.",
    "weekly": "Per week of each month in the period (1–7, 8–14, 15–21, 22–end).",
    "monthly": f"Per month of {c.month.year} (all published months, period filter ignored).",
    "yearly": "Per year across all published data (period filter ignored).",
}[period])

with st.spinner(f"Calculating {group} productivity ({PERIOD_LABEL[period].lower()})…", show_time=True):
    if scope == "month":
        ev, rit = c.ev, c.rit
    else:
        vers = c.versions_for(scope)
        ev = scope_filter(dash.combine("events", vers), c.allowed)
        rit = scope_filter(dash.combine("ritase", vers), c.allowed)
    if rit.empty or rit[rit["material_group"] == group].empty:
        st.info(f"No {group} trips for this selection.")
        st.stop()

    rit = with_week(rit)
    if period == "hourly":
        evb = split_hourly(ev)
        key = ["hour_slot"]
    else:
        evb = ev
        key = ["date"]
    # productivity per unit per base key (hour slot or date), then rolled up to the chosen period
    ld = productivity(rit, evb, "loader", key, group)
    hl = productivity(rit, evb, "hauler", key, group)
    for df in (ld, hl):
        if len(df):
            if period == "hourly":
                df["bucket"] = df["hour_slot"]
            else:
                tmp = with_week(df.assign(date=pd.to_datetime(df["date"])))
                df["bucket"] = bucket(tmp, period).to_numpy()

    fl = fleet_summary(ld, ["bucket"])
    fh = fleet_summary(hl, ["bucket"])
    order = bucket_order(fl.index, period)
    fl, fh = fl.reindex(order), fh.reindex(order)
    labels = [pretty(x, period) for x in order]

tot_l, tot_h = fleet_summary(ld, []), fleet_summary(hl, [])
material = "OB" if group == "OB" else "CG - Coal Getting"


def target_of(role: str, model) -> float | None:
    return (PT.model_target(model, material, ld_def, basis) if role == "loader"
            else PT.hauler_target(model, group, hl_def, basis))


def fleet_target(df: pd.DataFrame, role: str) -> float | None:
    """Ready-hour weighted default of the units that have one (the fleet's yardstick)."""
    if df.empty:
        return None
    u = df.groupby("unit").agg(model=("model", "first"), h=("ready_h", "sum"))
    u["t"] = [target_of(role, mo) for mo in u["model"]]
    u = u.dropna(subset=["t"])
    return float((u["t"] * u["h"]).sum() / u["h"].sum()) if len(u) and u["h"].sum() else None


tgt_l, tgt_h = fleet_target(ld, "loader"), fleet_target(hl, "hauler")
best = ld.groupby("unit").agg(v=("volume", "sum"), h=("ready_h", "sum"))
best = (best["v"] / best["h"].where(best["h"] > 0)).dropna().sort_values(ascending=False)
dash.summary(f"Loaders move {fmt_num(tot_l['per_hour'].iloc[0], 1)} {unit} per Ready hour and haulers "
             f"{fmt_num(tot_h['per_hour'].iloc[0], 1)} {unit}",
             f"average haul {fmt_num(tot_l['dist_h'].iloc[0] / 1000, 2)} km horizontal and "
             f"{fmt_num(tot_l['dist_v'].iloc[0])} m vertical",
             f"best loader {best.index[0]} at {fmt_num(best.iloc[0], 1)} {unit}/h" if len(best) else "")
k = st.columns(6)
k[0].metric(f"{group} volume", f"{fmt_num(tot_l['volume'].iloc[0])} {unit}")
k[1].metric("Trips", fmt_num(tot_l["rit"].iloc[0]))
dash.kpi(k[2], f"Loader {unit}/h", tot_l["per_hour"].iloc[0], tgt_l, kind="n1",
         help="Volume / loader Ready hours; target = default per model weighted by Ready hours")
dash.kpi(k[3], f"Hauler {unit}/h", tot_h["per_hour"].iloc[0], tgt_h, kind="n1",
         help="Volume / hauler Ready hours; target = default per model weighted by Ready hours")
k[4].metric("Horizontal distance", f"{fmt_num(tot_l['dist_h'].iloc[0])} m", "trip-weighted", delta_color="off")
k[5].metric("Vertical distance", f"{fmt_num(tot_l['dist_v'].iloc[0])} m", "trip-weighted", delta_color="off")

left, right = st.columns(2)
with left:
    fig = go.Figure()
    fig.add_bar(x=labels, y=fl["volume"], name=f"Volume ({unit})", marker_color=T.ACCENT if group == "OB" else T.READY,
                opacity=.55)
    fig.add_scatter(x=labels, y=fl["per_hour"], name=f"Loader {unit}/h", yaxis="y2", line=dict(color=T.PA_COLOR, width=3))
    fig.add_scatter(x=labels, y=fh["per_hour"], name=f"Hauler {unit}/h", yaxis="y2", line=dict(color=T.MISS, width=3))
    per = {"hourly": "hour", "daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}[period]
    fig.update_layout(title=f"{group} volume & productivity per {per}",
                      xaxis=dict(type="category"), yaxis=dict(title=unit),
                      yaxis2=dict(overlaying="y", side="right", title=f"{unit} per Ready hour"))
    dash.plot(fig, 380)
with right:
    fig = go.Figure()
    fig.add_scatter(x=labels, y=fl["dist_h"], name="Horizontal (m)", line=dict(color=T.PA_COLOR, width=3))
    fig.add_scatter(x=labels, y=fl["dist_v"], name="Vertical (m)", yaxis="y2", line=dict(color=T.ACCENT, width=3))
    fig.update_layout(title=f"{group} haul distance (trip-weighted)", xaxis=dict(type="category"),
                      yaxis=dict(title="horizontal (m)"), yaxis2=dict(overlaying="y", side="right", title="vertical (m)"))
    dash.plot(fig, 380)


def unit_table(df: pd.DataFrame, role: str) -> pd.DataFrame:
    g = df.groupby("unit").agg(model=("model", "first"), volume=("volume", "sum"), trips=("rit", "sum"),
                               ready_h=("ready_h", "sum"), work_h=("work_h", "sum"))
    w = df.assign(wh=df["dist_h"] * df["rit"], wv=df["dist_v"] * df["rit"]).groupby("unit")[["wh", "wv"]].sum()
    g["per_hour"] = g["volume"] / g["ready_h"].where(g["ready_h"] > 0)
    g["per_hour_work"] = g["volume"] / g["work_h"].where(g["work_h"] > 0)
    g["trips_per_hour"] = g["trips"] / g["ready_h"].where(g["ready_h"] > 0)
    g["dist_h"], g["dist_v"] = w["wh"] / g["trips"], w["wv"] / g["trips"]
    g["target"] = [target_of(role, mo) for mo in g["model"]]
    g["ach"] = g["per_hour"] / g["target"]
    g = g.reset_index().sort_values("volume", ascending=False)
    return g.rename(columns={"unit": role.title(), "model": "Model", "volume": f"Volume ({unit})", "trips": "Trips",
                             "ready_h": "Ready h", "work_h": "Ready+Idle h", "per_hour": f"{unit}/Ready h",
                             "per_hour_work": f"{unit}/(Ready+Idle) h", "trips_per_hour": "Trips/Ready h",
                             "dist_h": "Horizontal (m)", "dist_v": "Vertical (m)",
                             "target": f"Target {unit}/h", "ach": "Achievement"})


cfg = lambda cols: {x: st.column_config.NumberColumn(format="percent" if x == "Achievement" else "%,.1f")  # noqa: E731
                    for x in cols}
t1, t2 = st.tabs(["Loaders", "Haulers"])
with t1:
    tl = unit_table(ld, "loader")
    a, b = st.columns([1, 1.6])
    with a:
        dash.ranking(tl.dropna(subset=[f"{unit}/Ready h"]), "Loader", f"{unit}/Ready h", f"Loader {unit} per Ready hour",
                     T.ACCENT if group == "OB" else T.READY, pct=False, digits=1)
    with b:
        st.dataframe(tl, hide_index=True, width="stretch", height=420, column_config=cfg(tl.columns[2:]))
        excel_download(tl, f"loader_productivity_{group}_{period}.xlsx", key="dl_ld")
with t2:
    th = unit_table(hl, "hauler")
    mdl = hl.groupby("model").agg(volume=("volume", "sum"), ready_h=("ready_h", "sum"), rit=("rit", "sum")).reset_index()
    mdl["per_hour"] = mdl["volume"] / mdl["ready_h"].where(mdl["ready_h"] > 0)
    a, b = st.columns([1, 1.6])
    with a:
        dash.ranking(mdl.dropna(subset=["per_hour"]), "model", "per_hour", f"Hauler {unit} per Ready hour by model",
                     T.PA_COLOR, pct=False, digits=1)
    with b:
        st.dataframe(th, hide_index=True, width="stretch", height=420, column_config=cfg(th.columns[2:]))
        excel_download(th, f"hauler_productivity_{group}_{period}.xlsx", key="dl_hl")

st.caption(f"Targets: Production Data default productivity per model, {PT.BASIS_LABEL[basis].lower()} "
           "(Settings → Production targets); a unit without a default has no target. "
           "Ready hours come from the Equipment Events sheet. A unit working on both OB and CG in the same "
           f"{'hour' if period == 'hourly' else 'day'} has its hours shared by its trip share. "
           "Distances are averages weighted by trips.")
