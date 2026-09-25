"""Metrik kinerja alat. Semua agregat berbobot jam: Σ jam dulu, baru dibagi."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import DOWN, IDLE, READY, STANDBY


def _div(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(b > 0, a / np.where(b > 0, b, 1), np.nan)


def time_buckets(events: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """Jam R/I/S/D/T (+W) per grup. Baris NO DATA tidak dihitung."""
    ev = events[events["category"].isin([READY, IDLE, STANDBY, DOWN])]
    keys = by or []
    if keys:
        p = ev.pivot_table(index=keys, columns="category", values="hours", aggfunc="sum", fill_value=0.0,
                           observed=True)
    else:
        p = ev.groupby("category")["hours"].sum().to_frame().T
    p = p.reindex(columns=[READY, IDLE, STANDBY, DOWN], fill_value=0.0)
    p.columns.name = None
    p["W"] = p[READY] + p[IDLE]
    p["T"] = p["W"] + p[STANDBY] + p[DOWN]
    return p


def availability(buckets: pd.DataFrame) -> pd.DataFrame:
    """PA, UoA, MA, EU dari hasil time_buckets."""
    b = buckets
    out = b.copy()
    out["PA"] = _div(b["W"] + b[STANDBY], b["T"])
    out["UoA"] = _div(b["W"], b["W"] + b[STANDBY])
    out["MA"] = _div(b["W"], b["W"] + b[DOWN])
    out["EU"] = _div(b["W"], b["T"])
    return out


def kpis(events: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    return availability(time_buckets(events, by))


def reliability(events: pd.DataFrame, stoppages: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """MTBS, MTTR (stoppage SM+USM), MTBF (USM), Scheduled Down per grup."""
    b = time_buckets(events, by)
    st = stoppages.assign(is_usm=stoppages["usm_hours"] > 0)
    if by:
        g = st.groupby(by, observed=True)
        s = pd.DataFrame({"stoppages": g.size(), "usm_stoppages": g["is_usm"].sum(),
                          "down_hours": g["hours"].sum(), "sm_hours": g["sm_hours"].sum()})
        out = b.join(s, how="left")
    else:
        out = b.assign(stoppages=len(st), usm_stoppages=int(st["is_usm"].sum()),
                       down_hours=st["hours"].sum(), sm_hours=st["sm_hours"].sum())
    out[["stoppages", "usm_stoppages", "down_hours", "sm_hours"]] = (
        out[["stoppages", "usm_stoppages", "down_hours", "sm_hours"]].fillna(0))
    out["MTBS"] = _div(out["W"], out["stoppages"])
    out["MTTR"] = _div(out["down_hours"], out["stoppages"])
    out["MTBF"] = _div(out["W"], out["usm_stoppages"])
    out["SchedDown"] = _div(out["sm_hours"], out[DOWN])
    return out


def pm_accuracy(events: pd.DataFrame, intervals: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """PM (reason 502) akurat bila selisih HM sejak PM sebelumnya dalam interval ± toleransi%.

    `intervals`: kolom model, interval_hm, tolerance_pct. PM pertama per unit dan model tanpa
    interval tidak dinilai. Beberapa baris 502 berurutan = satu kejadian PM.
    """
    pm = events[events["reason_code"] == 502].sort_values(["unit_id", "seq"])
    pm = pm[pm["seq"] - pm.groupby("unit_id")["seq"].shift() != 1]  # awal tiap blok PM
    pm = pm.assign(prev_hm=pm.groupby("unit_id")["hm_start"].shift())
    pm = pm.merge(intervals, on="model", how="left")
    pm["gap"] = pm["hm_start"] - pm["prev_hm"]
    pm["assessable"] = pm["prev_hm"].notna() & pm["interval_hm"].notna() & pm["gap"].notna()
    tol = pm["interval_hm"] * pm["tolerance_pct"].fillna(10) / 100
    pm["accurate"] = pm["assessable"] & (pm["gap"] - pm["interval_hm"]).abs().le(tol)
    keys = by or []
    g = pm.groupby(keys, observed=True) if keys else pm.assign(_k=0).groupby("_k")
    out = pd.DataFrame({"pm_events": g.size(), "assessable": g["assessable"].sum(), "accurate": g["accurate"].sum()})
    out["PMAccuracy"] = _div(out["accurate"], out["assessable"])
    return out if keys else out.reset_index(drop=True)


def complete_days(events: pd.DataFrame, coverage: float = 0.95) -> pd.Series:
    """Per tanggal: True bila >= coverage unit aktif punya data di kedua shift (DS & NS)."""
    ev = events[events["category"] != "N"]
    active = ev["unit_id"].nunique()
    both = ev.groupby(["date", "unit_id"])["shift"].nunique().eq(2).groupby("date").sum()
    return both >= coverage * active if active else both.astype(bool)
