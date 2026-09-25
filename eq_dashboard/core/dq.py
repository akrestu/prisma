"""Aturan data quality. Hasil: satu baris per temuan (site, rule, severity, sheet, row_ref, unit_id, date, detail).

Severity:
- critical : menahan auto-approve (data berpotensi salah hitung)
- warn     : perlu dicek, tidak menahan auto-approve
- info     : sudah ditangani otomatis oleh aplikasi
"""
from __future__ import annotations

import pandas as pd

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
    out.append(_rows(ev[ev["category"] == NO_DATA], "status_kosong", "warn", "Eq.Event",
                     "Status/Total Jam kosong → tidak dihitung (NO DATA)"))
    day = (ev.groupby(["site", "unit_id", "date"])["hours"].sum().reset_index())
    out.append(_rows(day[day["hours"] > 24.01], "unit_hari_lebih_24_jam", "critical", "Eq.Event",
                     lambda r: f"Total {r['hours']:.1f} jam dalam sehari (kemungkinan input ganda)"))
    last = ev["date"].max()
    out.append(_rows(day[(day["hours"] < 23.99) & (day["date"] < last)], "unit_hari_kurang_24_jam", "warn",
                     "Eq.Event", lambda r: f"Hanya {r['hours']:.1f} jam tercatat"))
    un = ev[ev["site"] == UNMAPPED].drop_duplicates("unit_id")
    out.append(_rows(un, "unit_tanpa_site", "warn", "Eq.Event",
                     "Unit tidak ada di Populasi atau tanpa Site → UNMAPPED"))
    return out


def check_units(units: pd.DataFrame) -> list[pd.DataFrame]:
    u = units[units["site"] == UNMAPPED].assign(date=pd.NaT, row_ref=None)
    return [_rows(u, "populasi_tanpa_site", "warn", "Populasi Unit", "Kolom Site kosong")]


def check_ritasi(r: pd.DataFrame) -> list[pd.DataFrame]:
    out = []
    z = r[r["muatan"] <= 0].drop_duplicates("row_ref").rename(columns={"hauler": "unit_id"})
    out.append(_rows(z, "muatan_nol", "warn", "Ritasi Unit", "Muatan 0 → volume 0"))
    ul = r[r["site"] == UNMAPPED].drop_duplicates("loader").rename(columns={"loader": "unit_id"})
    out.append(_rows(ul, "loader_tanpa_site", "warn", "Ritasi Unit", "Loader tidak dikenali → UNMAPPED"))
    x = r[(r["site"] != r["site_hauler"]) & (r["site"] != UNMAPPED) & (r["site_hauler"] != UNMAPPED)]
    if not x.empty:
        s = x.groupby(["site", "site_hauler"])["volume"].sum().reset_index()
        out.append(pd.DataFrame({"site": s["site"], "rule": "produksi_lintas_site", "severity": "info",
                                 "sheet": "Ritasi Unit", "row_ref": None, "unit_id": None, "date": None,
                                 "detail": s.apply(lambda q: f"{q['volume']:,.0f} dari hauler site "
                                                             f"{q['site_hauler']} → dicatat ke site loader", axis=1)}))
    return out


def check_timbangan(t: pd.DataFrame) -> list[pd.DataFrame]:
    out = [_rows(t[t["cancelled"]].rename(columns={"dt_unit": "unit_id"}), "tiket_batal", "info",
                 "Data Timbangan", lambda r: f"Tiket {r['ticket_id']} BATAL ({r['ton']:.2f} t) dibuang")]
    ul = t[(t["site"] == UNMAPPED) & ~t["cancelled"]]
    if not ul.empty:
        s = ul.groupby("loader", dropna=False)["ton"].agg(["sum", "count"]).reset_index()
        out.append(pd.DataFrame({"site": UNMAPPED, "rule": "loader_tidak_dikenali", "severity": "warn",
                                 "sheet": "Data Timbangan", "row_ref": None, "unit_id": s["loader"], "date": None,
                                 "detail": s.apply(lambda q: f"{int(q['count'])} tiket, {q['sum']:,.1f} t → "
                                                             f"tambahkan alias ID", axis=1)}))
    return out


def check_fuel(f_raw_missing: int, f: pd.DataFrame, rc: pd.DataFrame) -> list[pd.DataFrame]:
    out = []
    if f_raw_missing:
        out.append(pd.DataFrame([{"site": UNMAPPED, "rule": "fuel_volume_kosong", "severity": "warn",
                                  "sheet": "Fuel Consume", "row_ref": None, "unit_id": None, "date": None,
                                  "detail": f"{f_raw_missing} baris tanpa volume dibuang"}]))
    out.append(_rows(f[f["outlier"]], "fuel_outlier", "warn", "Fuel Consume",
                     lambda r: f"{r['liters']:,.0f} L di atas P99 model {r['model']}"))
    out.append(_rows(f[f["site"] == UNMAPPED].drop_duplicates("unit_id"), "fuel_unit_tanpa_site", "warn",
                     "Fuel Consume", "Unit pengisian tidak ada di Populasi → UNMAPPED"))
    tk = rc[rc["site"] == UNMAPPED].rename(columns={"unit": "unit_id"}).drop_duplicates("unit_id")
    out.append(_rows(tk, "tangki_tanpa_site", "warn", "Fuel Receipt", "Tambahkan mapping tangki → site"))
    return out


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
