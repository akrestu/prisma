"""TV screen payload for one site (PUBLISHED data only) for a chosen period.

Period → data range and breakdown:
  hourly  = last complete day, per hour         daily   = current month, per day
  weekly  = current month, per week              monthly = current year, per month
  yearly  = all years, per year
"""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import metrics
from core.config import DOWN, UNMAPPED
from core.ingest import PUBLISHED
from core.periods import (PERIODS, bucket, bucket_order, fleet_summary, pretty, productivity, split_hourly,
                          with_week)
from core.targets import METRICS
from core.validate import HOUR_SLOTS
from db import models as m
from db.repo import frame


@dataclass
class Kpi:
    key: str
    label: str
    value: float | None
    unit: str
    target: float | None
    higher_better: bool = True
    sub: str = ""
    note: str = ""

    @property
    def status(self) -> str:
        """good | bad | none (no target or no value)"""
        if self.value is None or self.target is None or pd.isna(self.value):
            return "none"
        ok = self.value >= self.target if self.higher_better else self.value <= self.target
        return "good" if ok else "bad"


@dataclass
class TvData:
    site: str
    period: str = "daily"
    range_label: str = ""
    first_date: dt.date | None = None
    last_date: dt.date | None = None
    last_complete: dt.date | None = None
    updated_at: dt.datetime | None = None
    kpis: list[Kpi] = field(default_factory=list)
    trend: pd.DataFrame = field(default_factory=pd.DataFrame)       # label, PA, UoA, complete
    prod: pd.DataFrame = field(default_factory=pd.DataFrame)        # label, ob, coal, ob_plan, coal_plan
    productivity: dict = field(default_factory=dict)                # {"OB": {...}, "CG": {...}}
    by_type: pd.DataFrame = field(default_factory=pd.DataFrame)
    components: pd.DataFrame = field(default_factory=pd.DataFrame)
    bad_units: pd.DataFrame = field(default_factory=pd.DataFrame)
    footer: dict = field(default_factory=dict)
    uoa_target: float | None = None

    @property
    def empty(self) -> bool:
        return self.first_date is None


def _versions(s: Session, site: str) -> pd.DataFrame:
    return frame(s, select(m.UploadSite.upload_id, m.UploadSite.month, m.UploadSite.reviewed_at)
                 .where(m.UploadSite.site_code == site, m.UploadSite.status == PUBLISHED)
                 .order_by(m.UploadSite.month))


def _load(s: Session, site: str, ids: list[int]):
    E, St, R, C, F = m.FactEvent, m.FactStoppage, m.FactRitase, m.FactCoalTicket, m.FactFuel
    w = lambda t: (t.upload_id.in_(ids), t.site == site)  # noqa: E731
    ev = frame(s, select(E.date, E.shift, E.week, E.seq, E.unit_id, E.type, E.model, E.time_start, E.hours,
                         E.hm_start, E.status, E.category, E.reason_code, E.reason_text, E.upload_id).where(*w(E)))
    st_ = frame(s, select(St.unit_id, St.type, St.model, St.start_date, St.hours, St.sm_hours, St.usm_hours,
                          St.main_reason).where(*w(St)))
    rit = frame(s, select(R.date, R.hour_slot, R.shift, R.hauler, R.hauler_model, R.loader, R.loader_model,
                          R.material_group, R.rit, R.volume, R.dist_h, R.dist_v).where(*w(R)))
    coal = frame(s, select(C.date, C.shift, C.ton, C.time_in).where(*w(C)))
    fuel = frame(s, select(F.date, F.liters).where(*w(F)))
    return ev, st_, rit, coal, fuel


def _targets(s: Session, site: str, months: list[dt.date], weights: dict) -> dict:
    rows = frame(s, select(m.Target.year, m.Target.month, *[getattr(m.Target, c) for c in METRICS])
                 .where(m.Target.site == site))
    out = {}
    for c in METRICS:
        vals, ws = [], []
        for mo in months:
            r = rows[(rows["year"] == mo.year) & (rows["month"] == mo.month)] if len(rows) else rows
            if r.empty or pd.isna(r[c].iloc[0]):
                vals = None
                break
            vals.append(float(r[c].iloc[0]))
            ws.append(weights.get(mo, 1.0))
        out[c] = float(np.average(vals, weights=ws)) if vals and sum(ws) > 0 else (vals[0] if vals else None)
    return out


def _plan_daily(s: Session, site: str, months: list[dt.date]) -> pd.DataFrame:
    rows = frame(s, select(m.PlanProduction.year, m.PlanProduction.month, m.PlanProduction.date,
                           m.PlanProduction.ob_bcm, m.PlanProduction.coal_ton).where(m.PlanProduction.site == site))
    parts = []
    for mo in months:
        days = calendar.monthrange(mo.year, mo.month)[1]
        d = pd.DataFrame({"date": [dt.date(mo.year, mo.month, i) for i in range(1, days + 1)]})
        r = rows[(rows["year"] == mo.year) & (rows["month"] == mo.month)] if len(rows) else rows
        for col, src in (("ob_plan", "ob_bcm"), ("coal_plan", "coal_ton")):
            v = pd.Series(np.nan, index=d.index)
            if len(r):
                daily = r[r["date"].notna()].set_index("date")[src]
                v = d["date"].map(daily)
                monthly = r[r["date"].isna()][src]
                if monthly.notna().any():
                    v = v.fillna(monthly.sum() / days)
            d[col] = v
        parts.append(d)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["date", "ob_plan", "coal_plan"])


def _fmt_pct(v) -> str:
    return "—" if v is None or pd.isna(v) else f"{v * 100:.1f}%"


def build(s: Session, site: str, intervals: pd.DataFrame | None = None, period: str = "daily") -> TvData:
    period = period if period in PERIODS else "daily"
    tv = TvData(site=site, period=period)
    ver = _versions(s, site)
    if ver.empty:
        return tv
    latest = ver["month"].max()
    if period in ("hourly", "daily", "weekly"):
        ver = ver[ver["month"] == latest]
    elif period == "monthly":
        ver = ver[[mo.year == latest.year for mo in ver["month"]]]
    tv.updated_at = ver["reviewed_at"].max()
    ev, st_, rit, coal, fuel = _load(s, site, [int(x) for x in ver["upload_id"]])
    if ev.empty:
        return tv

    complete = metrics.complete_days(ev[ev["date"] >= latest]) if len(ev) else pd.Series(dtype=bool)
    tv.last_complete = complete[complete].index.max() if complete.any() else None
    if period == "hourly":
        day = tv.last_complete or ev["date"].max()
        ev, rit = ev[ev["date"] == day], rit[rit["date"] == day]
        coal, fuel = coal[coal["date"] == day], fuel[fuel["date"] == day]
        st_ = st_[st_["start_date"] == day]
        tv.range_label = f"{day:%d %b %Y} · last complete day, hourly"
    tv.first_date, tv.last_date = ev["date"].min(), ev["date"].max()
    if period != "hourly":
        span = {"daily": "month to date, daily", "weekly": "month to date, weekly",
                "monthly": "year to date, monthly", "yearly": "all data, yearly"}[period]
        tv.range_label = f"{tv.first_date:%d %b %Y} – {tv.last_date:%d %b %Y} · {span}"

    # breakdown frames
    evb = split_hourly(ev) if period == "hourly" else ev
    evb = evb.assign(bucket=bucket(evb, period))
    rit = with_week(rit)
    ritb = rit.assign(bucket=bucket(rit, period)) if len(rit) else rit.assign(bucket=pd.Series(dtype=str))
    if len(coal):
        if period == "hourly":
            # tickets without an entry time still count in totals, just not in the hourly breakdown
            h = pd.to_datetime(coal["time_in"]).dt.hour
            coal = coal.assign(hour_slot=h.map(lambda x: None if pd.isna(x) else f"{int(x):02d}-{(int(x) + 1) % 24:02d}"))
        coal = with_week(coal).assign(bucket=lambda d: bucket(d, period))
    else:
        coal = coal.assign(bucket=pd.Series(dtype=str))

    months = sorted({dt.date(d.year, d.month, 1) for d in ev["date"]})
    hours_by_month = ev.assign(mo=[dt.date(d.year, d.month, 1) for d in ev["date"]]).groupby("mo")["hours"].sum()
    t = _targets(s, site, months, hours_by_month.to_dict())
    tv.uoa_target = t["uoa"]

    k = metrics.kpis(ev).iloc[0]
    rel = metrics.reliability(ev, st_).iloc[0]
    iv = intervals if intervals is not None else pd.DataFrame(columns=["model", "interval_hm", "tolerance_pct"])
    pm = metrics.pm_accuracy(ev, iv)
    pm_row = pm.iloc[0] if len(pm) else None
    assessable = int(pm_row["assessable"]) if pm_row is not None else 0

    # sub line of the PA/UoA cards
    def sub_for(col: str) -> str:
        if period == "hourly":
            sh = metrics.kpis(ev, ["shift"])
            return " · ".join(f"{x}: {_fmt_pct(sh.loc[x, col])}" for x in ("DS", "NS") if x in sh.index)
        if period in ("daily", "weekly") and tv.last_complete:
            v = metrics.kpis(ev[ev["date"] == tv.last_complete])[col].iloc[0]
            return f"{tv.last_complete:%d %b}: {_fmt_pct(v)}"
        if period == "monthly":
            v = metrics.kpis(ev[ev["date"] >= latest])[col].iloc[0]
            return f"{latest:%b %Y}: {_fmt_pct(v)}"
        v = metrics.kpis(ev[[d.year == latest.year for d in ev["date"]]])[col].iloc[0]
        return f"{latest.year}: {_fmt_pct(v)}"

    ob_rows = ritb[ritb["material_group"] == "OB"] if len(ritb) else ritb
    ob_total = float(ob_rows["volume"].sum()) if len(ob_rows) else 0.0
    coal_total = float(coal["ton"].sum()) if len(coal) else 0.0
    plan = _plan_daily(s, site, months)
    plan = plan[(plan["date"] >= tv.first_date) & (plan["date"] <= tv.last_date)]
    ob_plan = plan["ob_plan"].sum(min_count=1) if len(plan) else np.nan      # plan for the whole range
    coal_plan = plan["coal_plan"].sum(min_count=1) if len(plan) else np.nan
    last_bucket = bucket_order(ritb["bucket"], period)[-1] if len(ritb) else None

    def prod_sub(series: pd.Series, unit: str) -> str:
        if last_bucket is None or series.empty:
            return ""
        v = series.get(last_bucket, 0.0)
        return f"{pretty(last_bucket, period)}: {v:,.0f} {unit}"

    ob_by = ob_rows.groupby("bucket")["volume"].sum() if len(ob_rows) else pd.Series(dtype=float)
    coal_by = coal.groupby("bucket")["ton"].sum() if len(coal) else pd.Series(dtype=float)
    tv.kpis = [
        Kpi("pa", "PA", k["PA"], "%", t["pa"], sub=sub_for("PA")),
        Kpi("uoa", "UoA", k["UoA"], "%", t["uoa"], sub=sub_for("UoA")),
        Kpi("mtbs", "MTBS", rel["MTBS"], "h", t["mtbs"], sub=f"{int(rel['stoppages']):,} stoppages"),
        Kpi("mttr", "MTTR", rel["MTTR"], "h", t["mttr"], higher_better=False, sub="lower is better"),
        Kpi("sched", "Sched. down", rel["SchedDown"], "%", t["sched_down"], sub="SM hours / down hours"),
        Kpi("pm", "PM accuracy", pm_row["PMAccuracy"] if assessable else None, "%", t["pm_accuracy"],
            sub=f"{int(pm_row['pm_events']) if pm_row is not None else 0} PM events",
            note="" if assessable else "PM intervals not set"),
        Kpi("ob", "OB", ob_total, "BCM", ob_plan if pd.notna(ob_plan) else None,
            sub=prod_sub(ob_by, "BCM"), note="" if pd.notna(ob_plan) else "no plan"),
        Kpi("coal", "Coal", coal_total, "t", coal_plan if pd.notna(coal_plan) else None,
            sub=prod_sub(coal_by, "t"), note="" if pd.notna(coal_plan) else "no plan"),
    ]

    # trend PA / UoA per bucket
    tr = metrics.kpis(evb, ["bucket"])[["PA", "UoA"]]
    order = bucket_order(tr.index, period)
    tr = tr.reindex(order).reset_index().rename(columns={"index": "bucket"})
    tr["label"] = [pretty(b, period) for b in tr["bucket"]]
    if period == "daily":
        tr["complete"] = [complete.get(pd.Timestamp(b).date(), True) for b in tr["bucket"]]
    else:
        tr["complete"] = True
    tv.trend = tr

    # production per bucket (+ plan per bucket)
    labels = (list(HOUR_SLOTS) if period == "hourly"  # always show the full production day
              else bucket_order(list(ob_by.index) + list(coal_by.index), period))
    pr = pd.DataFrame({"bucket": labels})
    pr["ob"] = pr["bucket"].map(ob_by).fillna(0.0)
    pr["coal"] = pr["bucket"].map(coal_by).fillna(0.0)
    if len(plan) and period != "hourly":
        pb = with_week(plan.assign(date=pd.to_datetime(plan["date"]))).assign(bucket=lambda d: bucket(d, period))
        pr["ob_plan"] = pr["bucket"].map(pb.groupby("bucket")["ob_plan"].sum(min_count=1))
        pr["coal_plan"] = pr["bucket"].map(pb.groupby("bucket")["coal_plan"].sum(min_count=1))
    elif len(plan):  # hourly: day plan spread evenly over 24 hours
        pr["ob_plan"], pr["coal_plan"] = ob_plan / 24, coal_plan / 24
    else:
        pr["ob_plan"] = pr["coal_plan"] = np.nan
    pr["label"] = [pretty(b, period) for b in pr["bucket"]]
    tv.prod = pr

    # productivity & distance (OB and CG) over the whole range
    evp = evb if period == "hourly" else ev
    by_hour = ["hour_slot"] if period == "hourly" else ["date"]
    ritp = rit
    for grp in ("OB", "CG"):
        ld = productivity(ritp, evp, "loader", by_hour, grp)
        hl = productivity(ritp, evp, "hauler", by_hour, grp)
        fl, fh = fleet_summary(ld, []), fleet_summary(hl, [])
        tv.productivity[grp] = {
            "volume": float(fl["volume"].iloc[0]) if len(fl) else 0.0,
            "rit": float(fl["rit"].iloc[0]) if len(fl) else 0.0,
            "loader_per_hour": float(fl["per_hour"].iloc[0]) if len(fl) else np.nan,
            "hauler_per_hour": float(fh["per_hour"].iloc[0]) if len(fh) else np.nan,
            "rit_per_hour": float(hl["rit"].sum() / hl["ready_h"].sum()) if len(hl) and hl["ready_h"].sum() else np.nan,
            "loaders": int(ld["unit"].nunique()) if len(ld) else 0,
            "haulers": int(hl["unit"].nunique()) if len(hl) else 0,
            "dist_h": float(fl["dist_h"].iloc[0]) if len(fl) else np.nan,
            "dist_v": float(fl["dist_v"].iloc[0]) if len(fl) else np.nan,
        }

    bt = metrics.kpis(ev.assign(type=ev["type"].fillna(UNMAPPED)), ["type"])
    bt = bt.assign(Rp=bt["R"] / bt["T"], Ip=bt["I"] / bt["T"], Sp=bt["S"] / bt["T"], Dp=bt["D"] / bt["T"])
    tv.by_type = bt.reset_index().sort_values("PA", ascending=False)

    dn = ev[ev["category"] == DOWN]
    tv.components = (dn.groupby("reason_text")["hours"].sum().sort_values(ascending=False).head(5)
                     .reset_index().rename(columns={"reason_text": "reason"}))
    span_hours = 24.0 * ((tv.last_date - tv.first_date).days + 1)
    by_unit = dn.groupby("unit_id").agg(hours=("hours", "sum"), model=("model", "first"))
    main = (dn.groupby(["unit_id", "reason_text"])["hours"].sum().reset_index()
              .sort_values("hours", ascending=False).drop_duplicates("unit_id").set_index("unit_id")["reason_text"])
    latest_cat = ev.sort_values(["date", "seq"]).groupby("unit_id").tail(1).set_index("unit_id")["category"]
    bu = by_unit.sort_values("hours", ascending=False).head(6)
    bu["reason"] = bu.index.map(main)
    bu["full_period"] = bu["hours"] >= 0.95 * span_hours
    bu["down_now"] = bu.index.to_series().map(latest_cat).eq(DOWN).to_numpy()
    tv.bad_units = bu.reset_index().rename(columns={"unit_id": "unit"})

    fuel_total = float(fuel["liters"].sum()) if len(fuel) else 0.0
    tv.footer = {
        "units": int(ev["unit_id"].nunique()),
        "down_now": int(latest_cat.eq(DOWN).sum()),
        "fuel": fuel_total,
        "fuel_ratio": fuel_total / ob_total if ob_total else None,
        "stoppages": int(rel["stoppages"]),
        "pm_events": int(pm_row["pm_events"]) if pm_row is not None else 0,
    }
    return tv
