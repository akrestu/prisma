"""Aturan data quality. Hasil: satu baris per temuan (site, rule, severity, sheet, row_ref, unit_id, date, detail).

Severity:
- critical : menahan auto-approve (data berpotensi salah hitung)
- warn     : perlu dicek, tidak menahan auto-approve
- info     : sudah ditangani otomatis oleh aplikasi
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import String

from core.config import NO_DATA, UNMAPPED

COLS = ["site", "rule", "severity", "sheet", "row_ref", "unit_id", "date", "detail"]


def _rows(df: pd.DataFrame, rule: str, severity: str, sheet: str, detail) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=COLS)
    d = df.apply(detail, axis=1) if callable(detail) else detail
    return pd.DataFrame({
        "site": df.get("site", UNMAPPED), "rule": rule, "severity": severity, "sheet": sheet,
        "row_ref": df.get("row_ref"), "unit_id": df.get("unit_id"), "date": df.get("date"), "detail": d,
    })


def check_events(ev: pd.DataFrame) -> list[pd.DataFrame]:
    out = []
    out.append(_rows(ev[ev["category"] == NO_DATA], "empty_status", "warn", "Equipment Events",
                     "Empty Status/Total Jam → not counted (NO DATA)"))
    day = (ev.groupby(["site", "unit_id", "date"])["hours"].sum().reset_index())
    out.append(_rows(day[day["hours"] > 24.01], "unit_day_over_24h", "critical", "Equipment Events",
                     lambda r: f"{r['hours']:.1f} hours in one day (likely duplicate entry)"))
    last = ev["date"].max()
    out.append(_rows(day[(day["hours"] < 23.99) & (day["date"] < last)], "unit_day_under_24h", "warn",
                     "Equipment Events", lambda r: f"Only {r['hours']:.1f} hours recorded"))
    un = ev[ev["site"] == UNMAPPED].drop_duplicates("unit_id")
    out.append(_rows(un, "unit_without_site", "warn", "Equipment Events",
                     "Unit not in Populasi or has no Site → UNMAPPED"))
    return out


def check_units(units: pd.DataFrame) -> list[pd.DataFrame]:
    u = units[units["site"] == UNMAPPED].assign(date=pd.NaT, row_ref=None)
    return [_rows(u, "populasi_without_site", "warn", "Unit Population", "Site column is empty")]


def check_ritasi(r: pd.DataFrame) -> list[pd.DataFrame]:
    out = []
    z = r[r["muatan"] <= 0].drop_duplicates("row_ref").rename(columns={"hauler": "unit_id"})
    out.append(_rows(z, "zero_muatan", "warn", "Hauler Trips", "Muatan is 0 → volume 0"))
    out.append(_rit_as_volume(r))
    ul = r[r["site"] == UNMAPPED].drop_duplicates("loader").rename(columns={"loader": "unit_id"})
    out.append(_rows(ul, "loader_without_site", "warn", "Hauler Trips", "Unknown loader → UNMAPPED"))
    return out


def _rit_as_volume(r: pd.DataFrame) -> pd.DataFrame:
    """Hour cells must hold trips. When nearly every cell of a site is a whole multiple of Muatan (and at least one
    load), the sheet was filled with volume: every figure would be Muatan times too high. Critical, so it is never
    auto-approved."""
    x = r[(r["muatan"] > 1) & (r["rit"] > 0)]
    rows = []
    for site, g in x.groupby("site"):
        if len(g) < 50:
            continue
        ratio = g["rit"] / g["muatan"]
        share = ((ratio >= 1) & ((ratio - ratio.round()).abs() < 1e-6)).mean()
        if share >= 0.95:
            rows.append({"site": site, "rule": "rit_is_volume", "severity": "critical", "sheet": "Hauler Trips",
                         "row_ref": None, "unit_id": None, "date": None,
                         "detail": f"{share:.0%} of hour cells are exact multiples of Muatan (median "
                                   f"{g['rit'].median():,.0f}): they look like volume, not trips. Divide the hour "
                                   "columns by Muatan and upload again."})
    return pd.DataFrame(rows)


def check_timbangan(t: pd.DataFrame) -> list[pd.DataFrame]:
    out = [_rows(t[t["cancelled"]].rename(columns={"dt_unit": "unit_id"}), "cancelled_ticket", "info",
                 "Coal Weighbridge", lambda r: f"Ticket {r['ticket_id']} cancelled/BATAL ({r['ton']:.2f} t) excluded")]
    ul = t[(t["site"] == UNMAPPED) & ~t["cancelled"]]
    if not ul.empty:
        s = ul.groupby("loader", dropna=False)["ton"].agg(["sum", "count"]).reset_index()
        out.append(pd.DataFrame({"site": UNMAPPED, "rule": "unknown_loader", "severity": "warn",
                                 "sheet": "Coal Weighbridge", "row_ref": None, "unit_id": s["loader"], "date": None,
                                 "detail": s.apply(lambda q: f"{int(q['count'])} tickets, {q['sum']:,.1f} t → "
                                                             f"add an ID alias", axis=1)}))
    return out


def check_fuel(f_raw_missing: int, f: pd.DataFrame, rc: pd.DataFrame) -> list[pd.DataFrame]:
    out = []
    if f_raw_missing:
        out.append(pd.DataFrame([{"site": UNMAPPED, "rule": "empty_fuel_volume", "severity": "warn",
                                  "sheet": "Fuel Consumption", "row_ref": None, "unit_id": None, "date": None,
                                  "detail": f"{f_raw_missing} rows without volume excluded"}]))
    out.append(_rows(f[f["outlier"]], "fuel_outlier", "warn", "Fuel Consumption",
                     lambda r: f"{r['liters']:,.0f} L above the P99 of model {r['model']}"))
    out.append(_rows(f[f["site"] == UNMAPPED].drop_duplicates("unit_id"), "fuel_unit_without_site", "warn",
                     "Fuel Consumption", "Refuelled unit not in Populasi → UNMAPPED"))
    tk = rc[rc["site"] == UNMAPPED].rename(columns={"unit": "unit_id"}).drop_duplicates("unit_id")
    out.append(_rows(tk, "tank_without_site", "warn", "Fuel Receipts", "Add a tank → site mapping"))
    return out


def dropped_rows(df: pd.DataFrame, sheet: str, what: str, sites: list[str]) -> list[pd.DataFrame]:
    """Rows clean_* removed because `what` was unreadable. Their figures are lost, so this is critical; a row whose
    site is unknown (or UNMAPPED, e.g. a blank unit) is reported to every site of the file (any of them may be the one missing data)."""
    gone = df.attrs.get("dropped", [])
    if not gone:
        return []
    by_site: dict[str, list[int]] = {}
    for row, site in gone:
        for s in [site] if site and site != UNMAPPED else (sites or [UNMAPPED]):
            by_site.setdefault(s, []).append(row)
    return [pd.DataFrame([{"site": s, "rule": "rows_dropped", "severity": "critical", "sheet": sheet,
                           "row_ref": rows[0], "unit_id": None, "date": None,
                           "detail": f"{len(rows)} row(s) without a readable {what} were left out (Excel row "
                                     f"{', '.join(map(str, rows[:10]))}{' …' if len(rows) > 10 else ''})"}])
            for s, rows in by_site.items()]


def fit_table(df: pd.DataFrame, model, sheet: str, skip: tuple[str, ...] = ("id", "upload_id", "month")
              ) -> tuple[pd.DataFrame, list[pd.DataFrame]]:
    """Make a cleaned sheet storable in `model`'s table: a row with an empty required column is left out (critical,
    or the database would refuse the whole month), text longer than its column is cut (warn)."""
    cols = [c for c in model.__table__.columns if c.key not in skip and c.key in df.columns]
    out, found = df, []
    req = [c.key for c in cols if not c.nullable]
    miss = out[req].isna()
    bad = miss.any(axis=1)
    if bad.any():
        b = out[bad].assign(_cols=miss[bad].apply(lambda r: ", ".join(r.index[r]), axis=1))
        found.append(_rows(b, "required_value_missing", "critical", sheet,
                           lambda r: f"Empty or unreadable {r['_cols']} → row left out"))
        out = out[~bad]
    for c in cols:
        n = c.type.length if isinstance(c.type, String) else None
        if n is None or not (out[c.key].dtype == object or pd.api.types.is_string_dtype(out[c.key])):
            continue
        long = out[c.key].map(lambda v, n=n: isinstance(v, str) and len(v) > n)
        if long.any():
            found.append(_rows(out[long].drop_duplicates(c.key), "text_too_long", "warn", sheet,
                               f"{c.key} longer than {n} characters → cut"))
            out = out.assign(**{c.key: out[c.key].where(~long, out[c.key].str[:n])})
    return out, found


def combine(parts: list[pd.DataFrame]) -> pd.DataFrame:
    parts = [p for p in parts if not p.empty]
    if not parts:
        return pd.DataFrame(columns=COLS)
    return pd.concat(parts, ignore_index=True)[COLS]


def summary(dq: pd.DataFrame) -> dict[str, dict[str, int]]:
    """{site: {critical: n, warn: n, info: n}}"""
    if dq.empty:
        return {}
    c = dq.groupby(["site", "severity"]).size().unstack(fill_value=0)
    return {s: {k: int(v) for k, v in row.items()} for s, row in c.iterrows()}
