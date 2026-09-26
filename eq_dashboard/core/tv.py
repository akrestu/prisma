"""Paket data layar TV untuk satu site (hanya data PUBLISHED, bulan terbaru)."""
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
from core.targets import target_for
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
    last: str = ""
    note: str = ""

    @property
    def status(self) -> str:
        """good | bad | none (tanpa target / tanpa nilai)"""
        if self.value is None or self.target is None or pd.isna(self.value):
            return "none"
        ok = self.value >= self.target if self.higher_better else self.value <= self.target
        return "good" if ok else "bad"


@dataclass
class TvData:
    site: str
    month: dt.date | None = None
    first_date: dt.date | None = None
    last_date: dt.date | None = None
    last_complete: dt.date | None = None
    updated_at: dt.datetime | None = None
    kpis: list[Kpi] = field(default_factory=list)
    daily: pd.DataFrame = field(default_factory=pd.DataFrame)       # date, PA, UoA, complete
    prod: pd.DataFrame = field(default_factory=pd.DataFrame)        # date, ob, coal, ob_plan, coal_plan
    by_type: pd.DataFrame = field(default_factory=pd.DataFrame)     # type, PA, R, I, S, D (porsi)
    components: pd.DataFrame = field(default_factory=pd.DataFrame)  # reason, hours
    bad_units: pd.DataFrame = field(default_factory=pd.DataFrame)   # unit, model, hours, reason, full_period, down_now
    footer: dict = field(default_factory=dict)
    uoa_target: float | None = None

    @property
    def empty(self) -> bool:
        return self.month is None


def _published_upload(s: Session, site: str) -> tuple[int, dt.date, dt.datetime] | None:
    row = s.execute(select(m.UploadSite.upload_id, m.UploadSite.month, m.UploadSite.reviewed_at)
                    .where(m.UploadSite.site_code == site, m.UploadSite.status == PUBLISHED)
                    .order_by(m.UploadSite.month.desc()).limit(1)).first()
    return tuple(row) if row else None


def _plan(s: Session, site: str, month: dt.date, dates: list[dt.date]) -> pd.DataFrame:
    rows = frame(s, select(m.PlanProduction.date, m.PlanProduction.ob_bcm, m.PlanProduction.coal_ton)
                 .where(m.PlanProduction.site == site, m.PlanProduction.year == month.year,
                        m.PlanProduction.month == month.month))
    out = pd.DataFrame({"date": dates, "ob_plan": np.nan, "coal_plan": np.nan})
    if rows.empty:
        return out
    days = calendar.monthrange(month.year, month.month)[1]
    monthly = rows[rows["date"].isna()]
    daily = rows[rows["date"].notna()].set_index("date")
    for col, src in (("ob_plan", "ob_bcm"), ("coal_plan", "coal_ton")):
        if len(daily):
            out[col] = out["date"].map(daily[src])
        if len(monthly) and monthly[src].notna().any():
            out[col] = out[col].fillna(monthly[src].sum() / days)
    return out


def build(s: Session, site: str, intervals: pd.DataFrame | None = None) -> TvData:
    tv = TvData(site=site)
    pub = _published_upload(s, site)
    if pub is None:
        return tv
    upload_id, month, reviewed = pub
    tv.month, tv.updated_at = month, reviewed

    E, St, R, C, F = m.FactEvent, m.FactStoppage, m.FactRitase, m.FactCoalTicket, m.FactFuel
    w = lambda t: (t.upload_id == upload_id, t.site == site)  # noqa: E731
    ev = frame(s, select(E.date, E.shift, E.seq, E.unit_id, E.type, E.model, E.hours, E.hm_start, E.status,
                         E.category, E.reason_code, E.reason_text).where(*w(E)))
    if ev.empty:
        return tv
    st_ = frame(s, select(St.unit_id, St.type, St.model, St.hours, St.sm_hours, St.usm_hours, St.main_reason)
                .where(*w(St)))
    rit = frame(s, select(R.date, R.material_group, func.sum(R.volume).label("volume"))
                .where(*w(R)).group_by(R.date, R.material_group))
    coal = frame(s, select(C.date, func.sum(C.ton).label("ton")).where(*w(C)).group_by(C.date))
    fuel = s.scalar(select(func.sum(F.liters)).where(*w(F))) or 0.0

    tv.first_date, tv.last_date = ev["date"].min(), ev["date"].max()
    complete = metrics.complete_days(ev)
    tv.last_complete = complete[complete].index.max() if complete.any() else None
    last = ev[ev["date"] == tv.last_complete] if tv.last_complete else ev.iloc[0:0]

    k = metrics.kpis(ev).iloc[0]
    kl = metrics.kpis(last).iloc[0] if len(last) else None
    rel = metrics.reliability(ev, st_).iloc[0]
    pm = metrics.pm_accuracy(ev, intervals if intervals is not None else
                             pd.DataFrame(columns=["model", "interval_hm", "tolerance_pct"]))
    pm_row = pm.iloc[0] if len(pm) else None
    t = target_for(s, site, month.year, month.month)
    tv.uoa_target = t["uoa"]

    ob_daily = rit[rit["material_group"] == "OB"].set_index("date")["volume"] if len(rit) else pd.Series(dtype=float)
    coal_daily = coal.set_index("date")["ton"] if len(coal) else pd.Series(dtype=float)
    dates = sorted(set(ob_daily.index) | set(coal_daily.index))
    prod = pd.DataFrame({"date": dates})
    prod["ob"] = prod["date"].map(ob_daily).fillna(0.0)
    prod["coal"] = prod["date"].map(coal_daily).fillna(0.0)
    prod = prod.merge(_plan(s, site, month, dates), on="date", how="left")
    tv.prod = prod
    prod_last = prod["date"].max() if len(prod) else None

    def last_txt(v, fmt):
        return f"{tv.last_complete:%d %b}: {fmt(v)}" if kl is not None and v is not None and not pd.isna(v) else ""

    pct = lambda v: f"{v * 100:.1f}%".replace(".", ",")  # noqa: E731
    ob_plan_mtd = prod["ob_plan"].sum(min_count=1) if len(prod) else None
    coal_plan_mtd = prod["coal_plan"].sum(min_count=1) if len(prod) else None
    assessable = int(pm_row["assessable"]) if pm_row is not None else 0
    tv.kpis = [
        Kpi("pa", "PA", k["PA"], "%", t["pa"], last=last_txt(kl["PA"] if kl is not None else None, pct)),
        Kpi("uoa", "UoA", k["UoA"], "%", t["uoa"], last=last_txt(kl["UoA"] if kl is not None else None, pct)),
        Kpi("mtbs", "MTBS", rel["MTBS"], "jam", t["mtbs"], last=f"{int(rel['stoppages']):,} stoppage MTD".replace(",", ".")),
        Kpi("mttr", "MTTR", rel["MTTR"], "jam", t["mttr"], higher_better=False, last="makin rendah makin baik"),
        Kpi("sched", "Sched. Down", rel["SchedDown"], "%", t["sched_down"], last="jam SM / jam down"),
        Kpi("pm", "PM Accuracy", pm_row["PMAccuracy"] if assessable else None, "%", t["pm_accuracy"],
            last=f"{int(pm_row['pm_events']) if pm_row is not None else 0} PM MTD",
            note="" if assessable else "interval PM belum diisi"),
        Kpi("ob", "OB", float(prod["ob"].sum()), "BCM", ob_plan_mtd if pd.notna(ob_plan_mtd or np.nan) else None,
            last=f"{prod_last:%d %b}: {prod.iloc[-1]['ob']:,.0f} BCM".replace(",", ".") if prod_last else "",
            note="" if pd.notna(ob_plan_mtd or np.nan) else "plan belum diisi"),
        Kpi("coal", "Coal", float(prod["coal"].sum()), "t", coal_plan_mtd if pd.notna(coal_plan_mtd or np.nan) else None,
            last=f"{prod_last:%d %b}: {prod.iloc[-1]['coal']:,.0f} t".replace(",", ".") if prod_last else "",
            note="" if pd.notna(coal_plan_mtd or np.nan) else "plan belum diisi"),
    ]

    d = metrics.kpis(ev, ["date"])[["PA", "UoA"]].reset_index()
    d["complete"] = d["date"].map(complete).fillna(False)
    tv.daily = d

    bt = metrics.kpis(ev.assign(type=ev["type"].fillna(UNMAPPED)), ["type"])
    bt = bt.assign(Rp=bt["R"] / bt["T"], Ip=bt["I"] / bt["T"], Sp=bt["S"] / bt["T"], Dp=bt["D"] / bt["T"])
    tv.by_type = bt.reset_index().sort_values("PA", ascending=False)

    dn = ev[ev["category"] == DOWN]
    tv.components = (dn.groupby("reason_text")["hours"].sum().sort_values(ascending=False).head(5)
                     .reset_index().rename(columns={"reason_text": "reason"}))

    hours_to_date = 24.0 * ((tv.last_complete or tv.last_date) - tv.first_date).days + 24.0
    by_unit = dn.groupby("unit_id").agg(hours=("hours", "sum"), model=("model", "first"))
    main = (dn.groupby(["unit_id", "reason_text"])["hours"].sum().reset_index()
              .sort_values("hours", ascending=False).drop_duplicates("unit_id").set_index("unit_id")["reason_text"])
    latest = ev.sort_values("seq").groupby("unit_id").tail(1).set_index("unit_id")["category"]
    bu = by_unit.sort_values("hours", ascending=False).head(6)
    bu["reason"] = bu.index.map(main)
    bu["full_period"] = bu["hours"] >= 0.95 * hours_to_date
    bu["down_now"] = bu.index.to_series().map(latest).eq(DOWN).to_numpy()
    tv.bad_units = bu.reset_index().rename(columns={"unit_id": "unit"})

    ob_total = float(prod["ob"].sum())
    tv.footer = {
        "units": int(ev["unit_id"].nunique()),
        "down_now": int(latest.eq(DOWN).sum()),
        "fuel": float(fuel),
        "fuel_ratio": fuel / ob_total if ob_total else None,
        "stoppages": int(rel["stoppages"]),
        "pm_events": int(pm_row["pm_events"]) if pm_row is not None else 0,
    }
    return tv
