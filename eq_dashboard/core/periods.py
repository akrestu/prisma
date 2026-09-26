"""Periods (hourly/daily/weekly/monthly/yearly), hourly split of events, productivity & haul distance."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import IDLE, READY
from core.validate import HOUR_SLOTS

PERIODS = ["hourly", "daily", "weekly", "monthly", "yearly"]
PERIOD_LABEL = {"hourly": "Hourly", "daily": "Daily", "weekly": "Weekly", "monthly": "Monthly", "yearly": "Yearly"}
UNIT = {"OB": "BCM", "CG": "t"}


def split_hourly(ev: pd.DataFrame) -> pd.DataFrame:
    """Split each event across production-hour slots (06-07 … 05-06).

    The production day starts at 06:00; night-shift times after midnight belong to the same production date.
    Returns one row per (event, slot) with the hours that fall inside that slot.
    """
    if ev.empty:
        return ev.assign(hour_slot=pd.Series(dtype=str))
    e = ev[ev["hours"] > 0].copy()
    t0 = e["time_start"].fillna(0.25).to_numpy() * 24.0
    start = np.where(t0 >= 6, t0 - 6, t0 + 18)  # hours since 06:00 of the production date
    end = np.minimum(start + e["hours"].to_numpy(), 24.0)
    first = np.floor(start).astype(int)
    last = np.maximum(np.ceil(end).astype(int) - 1, first)
    n = last - first + 1
    idx = np.repeat(np.arange(len(e)), n)
    slot = np.concatenate([np.arange(a, b + 1) for a, b in zip(first, last, strict=True)])
    s0, s1 = start[idx], end[idx]
    hrs = np.clip(np.minimum(s1, slot + 1) - np.maximum(s0, slot), 0, None)
    out = e.iloc[idx].copy()
    out["hours"] = hrs
    out["hour_slot"] = np.array(HOUR_SLOTS)[np.clip(slot, 0, 23)]
    return out[out["hours"] > 0].reset_index(drop=True)


def bucket(df: pd.DataFrame, period: str, date_col: str = "date") -> pd.Series:
    """Label per row for the chosen granularity (sortable)."""
    d = pd.to_datetime(df[date_col])
    if period == "hourly":
        return df["hour_slot"]
    if period == "daily":
        return d.dt.strftime("%Y-%m-%d")
    if period == "weekly":
        return d.dt.strftime("%Y-%m") + " " + df["week"] if "week" in df else d.dt.strftime("%G-W%V")
    if period == "monthly":
        return d.dt.strftime("%Y-%m")
    return d.dt.strftime("%Y")


def bucket_order(labels, period: str) -> list:
    labels = list(dict.fromkeys(labels))
    if period == "hourly":
        return [s for s in HOUR_SLOTS if s in set(labels)]
    return sorted(labels)


def pretty(label: str, period: str) -> str:
    if period == "daily":
        return pd.Timestamp(label).strftime("%d %b")
    if period == "weekly":
        return label.split(" ", 1)[1].replace("Week ", "W") if " " in label else label
    if period == "monthly":
        return pd.Timestamp(label + "-01").strftime("%b %Y")
    return label


def with_week(rit: pd.DataFrame) -> pd.DataFrame:
    """Ritase has no week column; derive it with the same rule as events (1–7, 8–14, 15–21, 22–end)."""
    from core.clean import week_of
    if rit.empty or "week" in rit:
        return rit
    return rit.assign(week=week_of(pd.to_datetime(rit["date"]).dt.day).to_numpy())


def weighted(df: pd.DataFrame, col: str, w: str = "rit") -> float:
    d = df[[col, w]].dropna()
    return float(np.average(d[col], weights=d[w])) if len(d) and d[w].sum() > 0 else np.nan


def productivity(rit: pd.DataFrame, ev_hourly_or_daily: pd.DataFrame, role: str, by: list[str],
                 group: str) -> pd.DataFrame:
    """Productivity of loaders or haulers for one material group (OB or CG).

    role: "loader" | "hauler"; by: extra grouping columns present in both frames (e.g. ["bucket"]).
    Working hours = Ready hours of the unit, shared between OB and CG by its ritase share in the same bucket.
    Returns volume, rit, ready hours, volume/hour (Ready), volume/hour (Ready+Idle), rit/hour, H & V distance.
    """
    if rit.empty:
        return pd.DataFrame()
    r = rit.rename(columns={role: "unit"})
    keys = ["unit", *by]
    tot = r.groupby(keys)["rit"].sum().rename("rit_all")
    g = r[r["material_group"] == group]
    if g.empty:
        return pd.DataFrame()
    agg = g.groupby(keys).agg(volume=("volume", "sum"), rit=("rit", "sum"),
                              model=(f"{role}_model", "first")).join(tot)
    agg["dist_h"] = g.groupby(keys).apply(lambda x: weighted(x, "dist_h"), include_groups=False)
    agg["dist_v"] = g.groupby(keys).apply(lambda x: weighted(x, "dist_v"), include_groups=False)
    ev = ev_hourly_or_daily.rename(columns={"unit_id": "unit"})
    hrs = ev.pivot_table(index=keys, columns="category", values="hours", aggfunc="sum", fill_value=0.0)
    ready = hrs.get(READY, pd.Series(0.0, index=hrs.index))
    work = ready + hrs.get(IDLE, pd.Series(0.0, index=hrs.index))
    share = agg["rit"] / agg["rit_all"]
    agg["ready_h"] = ready.reindex(agg.index).fillna(0) * share
    agg["work_h"] = work.reindex(agg.index).fillna(0) * share
    agg["per_hour"] = agg["volume"] / agg["ready_h"].replace(0, np.nan)
    agg["per_hour_work"] = agg["volume"] / agg["work_h"].replace(0, np.nan)
    agg["rit_per_hour"] = agg["rit"] / agg["ready_h"].replace(0, np.nan)
    return agg.drop(columns="rit_all").reset_index()


def fleet_summary(prod: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Fleet totals per bucket from productivity(): volume per Ready hour, rit-weighted distances."""
    if prod.empty:
        return pd.DataFrame()
    g = prod.groupby(by) if by else prod.assign(_k=0).groupby("_k")
    out = g.agg(volume=("volume", "sum"), rit=("rit", "sum"), ready_h=("ready_h", "sum"), work_h=("work_h", "sum"),
                units=("unit", "nunique"))
    out["per_hour"] = out["volume"] / out["ready_h"].replace(0, np.nan)
    out["dist_h"] = g.apply(lambda x: weighted(x, "dist_h"), include_groups=False)
    out["dist_v"] = g.apply(lambda x: weighted(x, "dist_v"), include_groups=False)
    return out if by else out.reset_index(drop=True)
