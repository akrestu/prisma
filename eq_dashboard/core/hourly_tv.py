"""Data for the hourly production TV screen of one site (flash data + official month to date).

Figures, all for OB (BCM), Coal (t), SR (BCM per t) and Distance (m, trip-weighted):
- Hour: the current production hour; target = hourly targets of the fleets working that hour.
- Daily: the production date so far; outlook = run rate per elapsed hour × 24; target = daily plan.
- MTD: approved Data_Prod ritase up to its last date, then flash data for the days after; target = plan to date.
- Outlook: MTD per elapsed day × days in the month; target = the month's plan.
"""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import hourly as H
from core.tv import _plan_daily
from db import models as m
from db import repo

GROUPS = {"OB": "Overburden", "CG": "Coal"}


@dataclass
class HourlyTv:
    site: str
    date: dt.date
    shift: str
    slot: int                           # current production hour 1..12 of the shift (0 = shift not started)
    live: bool                          # True when showing the shift that is running now
    coordinator: str = ""
    updated_at: dt.datetime | None = None
    updated_by: str | None = None
    summary: dict = field(default_factory=dict)     # {block: {metric: (actual, target, ach)}}
    daily_outlook: dict = field(default_factory=dict)
    fleets: dict = field(default_factory=dict)      # {"OB"/"CG": DataFrame}
    totals: dict = field(default_factory=dict)      # {"OB"/"CG": {"slots": [...], "running": [...], "total": x}}
    official_until: dt.date | None = None

    @property
    def empty(self) -> bool:
        return not any(len(df) for df in self.fleets.values())


def _ach(actual, target):
    if actual is None or target is None or pd.isna(actual) or pd.isna(target) or not target:
        return None
    return actual / target


def _dist(df: pd.DataFrame) -> float:
    d = df.dropna(subset=["distance_m"])
    w = d["rit"].sum()
    return float((d["distance_m"] * d["rit"]).sum() / w) if w else np.nan


def _triple(ob, cg, dist, t_ob, t_cg, t_sr, t_dist) -> dict:
    sr = ob / cg if cg else np.nan
    # achievement = actual ÷ target for every line, as on the site boards (SR 4.4 vs 12.8 → 34%)
    return {"OB": (ob, t_ob, _ach(ob, t_ob)), "Coal": (cg, t_cg, _ach(cg, t_cg)),
            "SR": (sr, t_sr, _ach(sr, t_sr)), "Distance": (dist, t_dist, _ach(dist, t_dist))}


def _official(s: Session, site: str, month: dt.date) -> pd.DataFrame:
    """Approved ritase of the month per date: ob, cg, rit-weighted distance numerator (dist_w) and trips."""
    r, us = m.FactRitase, m.UploadSite
    q = (select(r.date, r.material_group, func.sum(r.volume).label("vol"), func.sum(r.rit).label("rit"),
                func.sum(r.dist_h * r.rit).label("dist_w"))
         .join(us, (us.upload_id == r.upload_id) & (us.site_code == r.site))
         .where(r.site == site, r.month == month, us.status == "PUBLISHED")
         .group_by(r.date, r.material_group))
    return repo.frame(s, q)


def build(s: Session, site: str, now: dt.datetime, date: dt.date | None = None, shift: str | None = None) -> HourlyTv:
    p_date, p_shift, p_slot = H.production_hour(now)
    date, shift = date or p_date, shift or p_shift
    live = (date, shift) == (p_date, p_shift)
    slot = p_slot if live else 12
    tv = HourlyTv(site, date, shift, slot, live)

    month = date.replace(day=1)
    days_in_month = calendar.monthrange(date.year, date.month)[1]
    flash = repo.hourly_range(s, [site], month, date)
    long = H.to_long(flash) if len(flash) else H.to_long(pd.DataFrame())
    cur = flash[(flash["date"] == date) & (flash["shift"] == shift)] if len(flash) else flash
    if len(cur):
        boss = cur["coordinator"].iloc[0]
        boss = "" if boss is None or str(boss).strip().lower() in ("", "nan", "none") else str(boss).strip()
        tv.coordinator, tv.updated_at, tv.updated_by = (boss, cur["updated_at"].max(),
                                                          cur["updated_by"].iloc[0])

    tgt = s.execute(select(m.Target.sr, m.Target.distance).where(
        m.Target.site == site, m.Target.year == date.year, m.Target.month == date.month)).first()
    t_sr, t_dist = (tgt.sr, tgt.distance) if tgt else (None, None)
    plan = _plan_daily(s, site, [month])
    plan_day = plan[plan["date"] == date]
    p_ob = float(plan_day["ob_plan"].iloc[0]) if len(plan_day) and pd.notna(plan_day["ob_plan"].iloc[0]) else None
    p_cg = float(plan_day["coal_plan"].iloc[0]) if len(plan_day) and pd.notna(plan_day["coal_plan"].iloc[0]) else None

    # ---- current hour
    lc = long[(long["date"] == date) & (long["shift"] == shift)] if len(long) else long
    hour = lc[lc["slot"] == slot] if len(lc) else lc
    working = hour[hour["rit"] > 0] if len(hour) else hour

    def hour_target(g):
        w = working[working["material_group"] == g]
        return float(w.drop_duplicates("loader")["target_per_hour"].sum()) if len(w) else None

    h_ob = float(hour.loc[hour["material_group"] == "OB", "volume"].sum()) if len(hour) else 0.0
    h_cg = float(hour.loc[hour["material_group"] == "CG", "volume"].sum()) if len(hour) else 0.0
    tv.summary["Hour"] = _triple(h_ob, h_cg, _dist(hour) if len(hour) else np.nan, hour_target("OB"),
                                 hour_target("CG"), t_sr, t_dist)

    # ---- production date (both shifts so far)
    ld = long[long["date"] == date] if len(long) else long
    d_ob = float(ld.loc[ld["material_group"] == "OB", "volume"].sum()) if len(ld) else 0.0
    d_cg = float(ld.loc[ld["material_group"] == "CG", "volume"].sum()) if len(ld) else 0.0
    elapsed = (slot if shift == "DS" else 12 + slot) if live else 24
    k = 24 / elapsed if elapsed else np.nan
    tv.summary["Daily"] = _triple(d_ob, d_cg, _dist(ld) if len(ld) else np.nan, p_ob, p_cg, t_sr, t_dist)
    tv.daily_outlook = {"OB": d_ob * k, "Coal": d_cg * k}

    # ---- month to date: official Data_Prod first, flash for the days after it
    off = _official(s, site, month)
    off = off[off["date"] <= date] if len(off) else off
    tv.official_until = off["date"].max() if len(off) else None
    fl = long[long["date"] > tv.official_until] if tv.official_until and len(long) else long
    fl_agg = (fl.assign(dist_w=fl["distance_m"].fillna(0) * fl["rit"])
                .groupby("material_group")[["volume", "rit", "dist_w"]].sum()) if len(fl) else pd.DataFrame()
    off_agg = off.groupby("material_group")[["vol", "rit", "dist_w"]].sum().rename(columns={"vol": "volume"}) \
        if len(off) else pd.DataFrame()
    tot = off_agg.add(fl_agg, fill_value=0) if len(off_agg) or len(fl_agg) else pd.DataFrame()
    mtd_ob = float(tot.loc["OB", "volume"]) if "OB" in tot.index else 0.0
    mtd_cg = float(tot.loc["CG", "volume"]) if "CG" in tot.index else 0.0
    ob_rit = float(tot.loc["OB", "rit"]) if "OB" in tot.index else 0.0
    mtd_dist = float(tot.loc["OB", "dist_w"]) / ob_rit if ob_rit else np.nan
    to_date = plan[plan["date"] <= date]
    t_ob_mtd = to_date["ob_plan"].sum(min_count=1)
    t_cg_mtd = to_date["coal_plan"].sum(min_count=1)
    tv.summary["MTD"] = _triple(mtd_ob, mtd_cg, mtd_dist, None if pd.isna(t_ob_mtd) else float(t_ob_mtd),
                                None if pd.isna(t_cg_mtd) else float(t_cg_mtd), t_sr, t_dist)
    days_done = (date - month).days + (elapsed / 24)
    f = days_in_month / days_done if days_done else np.nan
    m_ob, m_cg = plan["ob_plan"].sum(min_count=1), plan["coal_plan"].sum(min_count=1)
    tv.summary["Outlook"] = _triple(mtd_ob * f, mtd_cg * f, mtd_dist, None if pd.isna(m_ob) else float(m_ob),
                                    None if pd.isna(m_cg) else float(m_cg), t_sr, t_dist)

    # ---- fleet tables for the shift on screen
    for g in GROUPS:
        rows = cur[cur["material_group"] == g] if len(cur) else cur
        tv.fleets[g], tv.totals[g] = _fleet_table(rows, lc[lc["material_group"] == g] if len(lc) else lc)
    return tv


def _fleet_table(rows: pd.DataFrame, long: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """One row per loader (fleet) with volume per hour, plus shift totals. `target_slots` is the hourly target of
    the fleets that worked in each hour (the yardstick of the hourly bars and the burn-up line)."""
    empty = {"slots": [0.0] * 12, "running": [0] * 12, "target_slots": [0.0] * 12, "total": 0.0, "haulers": 0,
             "trips": 0.0}
    if rows.empty:
        return pd.DataFrame(), empty
    vol = long.pivot_table(index="loader", columns="slot", values="volume", aggfunc="sum", fill_value=0.0)         .reindex(columns=range(1, 13), fill_value=0.0)
    vol.columns = [f"s{k}" for k in range(1, 13)]          # string names: itertuples renames integer columns
    rows = rows.assign(hauler_key=rows["hauler"].fillna(rows["hauler_model"]) if "hauler" in rows
                       else rows["hauler_model"])
    first = rows.sort_values("line").groupby("loader", sort=False).agg(
        model=("loader_model", "first"), material=("material", lambda x: " / ".join(dict.fromkeys(x.dropna()))),
        pit=("pit", "first"), disposal=("disposal", "first"), target=("target_per_hour", "max"),
        operator=("operator", lambda x: ", ".join(dict.fromkeys(x.dropna()))),
        haulers=("hauler_key", "nunique"),
        hauler_ids=("hauler_key", lambda x: " ".join(dict.fromkeys(str(v) for v in x.dropna()))),
        code=("remark_code", "first"), remark=("remark", lambda x: "; ".join(dict.fromkeys(x.dropna()))),
        line=("line", "min"))
    out = first.join(vol).sort_values("line").reset_index()
    cols = [f"s{k}" for k in range(1, 13)]
    out["total"] = out[cols].sum(axis=1)
    label = {k: f"{k} - {v}" for k, v in H.REMARKS.items()}
    out["remark"] = [" · ".join(x for x in (label.get(str(c), c if pd.notna(c) else None), r or None) if x)
                     for c, r in zip(out["code"], out["remark"], strict=True)]
    tgt = out["target"].fillna(0)
    totals = {"slots": [float(out[c].sum()) for c in cols],
              "running": [int((out[c] > 0).sum()) for c in cols],
              "target_slots": [float(tgt[out[c] > 0].sum()) for c in cols],
              "total": float(out["total"].sum()),
              "haulers": int(rows["hauler_key"].nunique()),
              "trips": float(long["rit"].sum()) if len(long) else 0.0}
    return out, totals
