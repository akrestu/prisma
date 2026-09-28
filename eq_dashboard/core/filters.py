"""Dashboard period presets and filter (de)serialisation for the URL and the per-user default. No Streamlit here.

Relative presets count back from the last date that has data (the anchor), not from today: uploads always lag a
few days, and "last 7 days" should never be half empty.
"""
from __future__ import annotations

import contextlib
import datetime as dt

PRESETS: dict[str, str] = {
    "last_day": "Last complete day",
    "last7": "Last 7 days",
    "mtd": "Month to date",
    "last_month": "Last month",
    "ytd": "Year to date",
    "custom": "Custom range",
}
DEFAULT_PRESET = "mtd"
# session/widget keys → URL parameter names; list values are comma-separated in the URL
FIELDS = {"f_site": "site", "f_period": "period", "f_week": "week", "f_shift": "shift", "f_type": "type",
          "f_model": "model", "f_unit": "unit"}
LIST_FIELDS = {"f_site", "f_week", "f_shift", "f_type", "f_model", "f_unit"}


def month_start(d: dt.date) -> dt.date:
    return d.replace(day=1)


def month_end(d: dt.date) -> dt.date:
    nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return nxt - dt.timedelta(days=1)


def preset_range(key: str, anchor: dt.date, first: dt.date, last_complete: dt.date | None = None,
                 custom: tuple[dt.date, dt.date] | None = None) -> tuple[dt.date, dt.date]:
    """(from, to) for a preset, clamped to the data that exists [first, anchor]."""
    if key == "last_day":
        d0 = d1 = last_complete or anchor
    elif key == "last7":
        d0, d1 = anchor - dt.timedelta(days=6), anchor
    elif key == "last_month":
        d1 = month_start(anchor) - dt.timedelta(days=1)
        d0 = month_start(d1)
    elif key == "ytd":
        d0, d1 = anchor.replace(month=1, day=1), anchor
    elif key == "custom" and custom:
        d0, d1 = sorted(custom)
    else:                                              # mtd and anything unknown
        d0, d1 = month_start(anchor), anchor
    d0, d1 = max(d0, first), min(d1, anchor)
    if d0 > d1:                                        # e.g. "last month" when only this month exists
        d0 = d1 = anchor
    return d0, d1


def months_between(d0: dt.date, d1: dt.date) -> list[dt.date]:
    out, m = [], month_start(d0)
    while m <= d1:
        out.append(m)
        m = month_end(m) + dt.timedelta(days=1)
    return out


def range_label(d0: dt.date, d1: dt.date) -> str:
    """'1 – 23 Sep 2026', '20 Aug – 10 Sep 2026', '5 Dec 2025 – 3 Jan 2026', '22 Sep 2026'."""
    if d0 == d1:
        return f"{d1.day} {d1:%b %Y}"   # day built by hand: '%-d' does not work on Windows
    if d0.year != d1.year:
        return f"{d0.day} {d0:%b %Y} – {d1.day} {d1:%b %Y}"
    if d0.month != d1.month:
        return f"{d0.day} {d0:%b} – {d1.day} {d1:%b %Y}"
    return f"{d0.day} – {d1.day} {d1:%b %Y}"


def to_query(state: dict) -> dict[str, str]:
    """Filter state (session keys) → URL parameters. Empty values are left out to keep links short."""
    q = {}
    for key, name in FIELDS.items():
        v = state.get(key)
        if v in (None, "", [], ()):
            continue
        q[name] = ",".join(map(str, v)) if key in LIST_FIELDS else str(v)
    rng = state.get("f_range")
    if state.get("f_period") == "custom" and isinstance(rng, (list, tuple)) and len(rng) == 2:
        q["from"], q["to"] = rng[0].isoformat(), rng[1].isoformat()
    return q


def from_query(params: dict) -> dict:
    """URL parameters → filter state. Unknown or malformed values are dropped (links are user input)."""
    state: dict = {}
    for key, name in FIELDS.items():
        raw = params.get(name)
        if not raw:
            continue
        raw = str(raw)[:2000]
        state[key] = [x for x in raw.split(",") if x] if key in LIST_FIELDS else raw
    if state.get("f_period") not in PRESETS:
        state.pop("f_period", None)
    try:
        d0, d1 = dt.date.fromisoformat(str(params["from"])), dt.date.fromisoformat(str(params["to"]))
        state["f_range"] = (min(d0, d1), max(d0, d1))
    except (KeyError, ValueError, TypeError):
        pass
    return state


def to_saved(state: dict) -> dict:
    """JSON-safe copy for users.default_filters (dates as ISO strings)."""
    return from_query(to_query(state)) | ({"f_range": [d.isoformat() for d in state["f_range"]]}
                                          if state.get("f_period") == "custom" and state.get("f_range") else {})


def from_saved(saved: dict | None) -> dict:
    if not saved:
        return {}
    out = {k: v for k, v in saved.items() if k in FIELDS}
    if saved.get("f_range"):
        with contextlib.suppress(TypeError, ValueError):
            out["f_range"] = tuple(dt.date.fromisoformat(x) for x in saved["f_range"])
    return out
