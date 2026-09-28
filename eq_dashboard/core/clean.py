"""Cleaning each Data_Prod sheet into tidy, site-tagged fact tables."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from core.config import DOWN, NO_DATA, STATUS_TO_CATEGORY, UNMAPPED
from core.io import day_fraction, excel_date, num, text
from core.validate import HOUR_SLOTS

SHIFT_MAP = {"day": "DS", "night": "NS", "ds": "DS", "ns": "NS", "i": "DS", "ii": "NS"}
DS_SLOTS = set(HOUR_SLOTS[:12])  # 06-07 .. 17-18


def week_of(day: pd.Series) -> pd.Series:
    """Minggu dalam bulan: 1–7, 8–14, 15–21, 22–akhir."""
    return pd.Series(np.select([day <= 7, day <= 14, day <= 21], ["Week 1", "Week 2", "Week 3"], "Week 4"),
                     index=day.index)


def week_of_legacy(day: pd.Series) -> pd.Series:
    """Definisi lama di file Excel (1–7, 8–15, 16–21, 22–akhir). Hanya untuk golden test."""
    return pd.Series(np.select([day <= 7, day <= 15, day <= 21], ["Week 1", "Week 2", "Week 3"], "Week 4"),
                     index=day.index)


def _shift(s: pd.Series) -> pd.Series:
    return text(s).str.lower().map(SHIFT_MAP)


def _ids(s: pd.Series, alias: dict[str, str] | None = None) -> pd.Series:
    """ID unit: strip, huruf besar, hapus spasi di tengah ('WDT 010' → 'WDT010'), lalu alias."""
    out = text(s).str.upper().str.replace(r"\s+", "", regex=True)
    return out.replace(alias) if alias else out


def month_start(d: pd.Series) -> pd.Series:
    return pd.to_datetime(d).dt.to_period("M").dt.to_timestamp().dt.date


# ------------------------------------------------------------------ Populasi Unit
def clean_units(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "unit_id": _ids(df["Equipment"]),
        "type": text(df["Type"]),
        "description": text(df["Description"]),
        "model": text(df["Model"]),
        "manufacturer": text(df["Manufacturer"]),
        "site": text(df["Site"]).fillna(UNMAPPED),
    })
    return out.dropna(subset=["unit_id"]).drop_duplicates("unit_id").reset_index(drop=True)


def _lookup(ids: pd.Series, units: pd.DataFrame, col: str, default=None) -> pd.Series:
    m = dict(zip(units["unit_id"], units[col], strict=True))
    out = ids.map(m)
    return out.fillna(default) if default is not None else out


# ------------------------------------------------------------------ Eq.Event
def clean_events(df: pd.DataFrame, units: pd.DataFrame, week_fn=week_of) -> pd.DataFrame:
    dt_ = excel_date(df["Date"])
    unit = _ids(df["Unit ID"])
    status = text(df["Status"])
    reason = text(df["Reason"])
    code = num(reason.str.extract(r"^\s*(\d{3})", expand=False))
    t0 = day_fraction(df["Jam Awal"])
    shift = _shift(df["Shift"])
    model_file = text(df["Model.1"]) if "Model.1" in df.columns else pd.Series(pd.NA, index=df.index)
    out = pd.DataFrame({
        "row_ref": df["_row"],  # Excel row number (io.frame)
        "date": dt_.dt.date,
        "shift": shift,
        "week": week_fn(dt_.dt.day),
        "unit_id": unit,
        "type": _lookup(unit, units, "type"),
        "model": _lookup(unit, units, "model").fillna(model_file),
        "site": _lookup(unit, units, "site", UNMAPPED),
        "operator": text(df["Operator"]),
        "time_start": t0,
        "time_end": day_fraction(df["Jam Akhir"]),
        "hours": num(df["Total Jam"]).fillna(0.0),
        "hm_start": num(df["HM awal"]),
        "hm_end": num(df["HM Akhir"]),
        "status": status,
        "category": status.map(STATUS_TO_CATEGORY).fillna(NO_DATA),
        "reason_code": code.astype("Int64"),
        "reason_text": reason.str.replace(r"^\s*\d{3}\s*", "", regex=True).str.strip(),
        "down_type": status.map({"SM": "Schedule", "USM": "Unschedule"}),
    })
    out = out.dropna(subset=["date", "unit_id"])
    out["month"] = month_start(out["date"])
    # urutan kronologis: shift malam melewati tengah malam (jam < 12:00 = setelah 00:00)
    t = out["time_start"].fillna(0.0)
    tkey = np.where((out["shift"] == "NS") & (t < 0.5), t + 1.0, t)
    out = (out.assign(_s=(out["shift"] == "NS").astype(int), _t=tkey)
              .sort_values(["unit_id", "date", "_s", "_t", "row_ref"], kind="stable")
              .drop(columns=["_s", "_t"]))
    out["seq"] = out.groupby("unit_id").cumcount()
    return out.reset_index(drop=True)


def build_stoppages(events: pd.DataFrame) -> pd.DataFrame:
    """Blok down (SM/USM) berurutan per unit = 1 stoppage. Events harus sudah terurut (clean_events)."""
    ev = events[events["category"] != NO_DATA]
    is_d = ev["category"] == DOWN
    block = (is_d != is_d.groupby(ev["unit_id"]).shift(fill_value=False)).cumsum()
    d = ev[is_d].assign(block=block[is_d])
    if d.empty:
        return pd.DataFrame(columns=["unit_id", "site", "type", "model", "month", "start_date", "start_shift",
                                     "end_date", "hours", "sm_hours", "usm_hours", "main_reason", "hm_start"])
    d = d.assign(sm=np.where(d["status"] == "SM", d["hours"], 0.0),
                 usm=np.where(d["status"] == "USM", d["hours"], 0.0))
    main = (d.groupby(["block", "reason_text"], dropna=False)["hours"].sum().reset_index()
              .sort_values("hours", ascending=False).drop_duplicates("block").set_index("block")["reason_text"])
    g = d.groupby("block")
    st = pd.DataFrame({
        "unit_id": g["unit_id"].first(), "site": g["site"].first(), "type": g["type"].first(),
        "model": g["model"].first(), "month": g["month"].first(),
        "start_date": g["date"].first(), "start_shift": g["shift"].first(), "end_date": g["date"].last(),
        "hours": g["hours"].sum(), "sm_hours": g["sm"].sum(), "usm_hours": g["usm"].sum(),
        "hm_start": g["hm_start"].first(),
    })
    st["main_reason"] = main
    return st.reset_index(drop=True)


# ------------------------------------------------------------------ Ritasi
def material_group(material: pd.Series) -> pd.Series:
    m = material.fillna("").str.upper()
    return pd.Series(np.select([m.str.startswith("OB"), m.str.startswith("CG")], ["OB", "CG"], "Other"),
                     index=material.index)


def clean_ritasi(df: pd.DataFrame, units: pd.DataFrame, alias: dict[str, str] | None = None) -> pd.DataFrame:
    dt_ = excel_date(df["Date"])
    base = pd.DataFrame({
        "row_ref": df["_row"],
        "date": dt_.dt.date,
        "hauler": _ids(df["EqNumber"], alias),
        "hauler_model": text(df["EqModel"]),
        "muatan": num(df["Muatan"]).fillna(0.0),
        "loader": _ids(df["Loader"], alias),
        "loader_model": text(df["Loader Model"]),
        "material": text(df["Material"]),
        "pit": text(df["Lokasi Loader"]),
        "disposal": text(df["Disposal"]),
        "dist_v": num(df["V Distance"]),
        "dist_h": num(df["H Distance"]),
    })
    hours = df[HOUR_SLOTS].apply(num)
    long = pd.concat([base, hours], axis=1).melt(id_vars=list(base.columns), value_vars=HOUR_SLOTS,
                                                 var_name="hour_slot", value_name="rit")
    long = long[long["rit"].fillna(0) > 0].dropna(subset=["date"]).copy()
    long["shift"] = np.where(long["hour_slot"].isin(DS_SLOTS), "DS", "NS")
    long["volume"] = long["rit"] * long["muatan"]
    long["material_group"] = material_group(long["material"])
    long["unit_vol"] = np.where(long["material_group"] == "CG", "ton", "BCM")
    long["site"] = _lookup(long["loader"], units, "site", UNMAPPED)
    long["site_hauler"] = _lookup(long["hauler"], units, "site", UNMAPPED)
    long["month"] = month_start(long["date"])
    return long.reset_index(drop=True)


# ------------------------------------------------------------------ Timbangan
SEAM_RE = re.compile(r"SEAM\s*([A-Z0-9]+)", re.I)


def clean_timbangan(df: pd.DataFrame, units: pd.DataFrame, alias: dict[str, str] | None = None) -> pd.DataFrame:
    dt_ = excel_date(df["Date"])
    product = text(df["Nama Product"])
    out = pd.DataFrame({
        "row_ref": df["_row"],
        "date": dt_.dt.date,
        "shift": _shift(df["Shift"]),
        "ticket_id": text(df["No. ID."]),
        "supplier": text(df["Nama Supplier"]),
        "product": product,
        "seam": product.str.upper().str.extract(SEAM_RE, expand=False).radd("SEAM "),
        "dt_unit": _ids(df["Convert DT"], alias),
        "loader": _ids(df["Loader"], alias),
        "ton": num(df["Tone"]),
        "time_in": excel_date(df["Tanggal / Jam Masuk"]),
        "time_out": excel_date(df["Tanggal / Jam Keluar"]),
        "dist_h": num(df["H Distance"]),
        "dist_v": num(df["V Distance"]),
    }).dropna(subset=["date"])
    out["cancelled"] = out["supplier"].str.upper().eq("BATAL").fillna(False)
    out["site"] = _lookup(out["loader"], units, "site", UNMAPPED)
    out["site_dt"] = _lookup(out["dt_unit"], units, "site", UNMAPPED)
    out["month"] = month_start(out["date"])
    return out.reset_index(drop=True)


# ------------------------------------------------------------------ Fuel
def clean_fuel(df: pd.DataFrame, units: pd.DataFrame, alias: dict[str, str] | None = None) -> pd.DataFrame:
    dt_ = excel_date(df["DATE"])
    unit = _ids(df["UNIT"], alias)
    out = pd.DataFrame({
        "row_ref": df["_row"],
        "date": dt_.dt.date,
        "shift": _shift(df["SHIFT"]),
        "time": day_fraction(df["TIME"]),
        "unit_id": unit,
        "type": _lookup(unit, units, "type"),
        "model": _lookup(unit, units, "model").fillna(text(df["MODEL"])),
        "liters": num(df["FLUID CONSUMPTION"]),
        "site": _lookup(unit, units, "site", UNMAPPED),
    }).dropna(subset=["date", "unit_id"])
    out["month"] = month_start(out["date"])
    p99 = out.groupby("model")["liters"].transform(lambda s: s.quantile(0.99) if s.count() >= 20 else np.inf)
    out["outlier"] = (out["liters"] > p99).fillna(False)
    return out.reset_index(drop=True)


def clean_receipt(df: pd.DataFrame, units: pd.DataFrame, tank_site: dict[str, str] | None = None) -> pd.DataFrame:
    dt_ = excel_date(df["DATE_RECEIPT"])
    unit = _ids(df["UNIT"])
    site = _lookup(unit, units, "site")
    if tank_site:
        site = site.fillna(unit.map(tank_site))
    out = pd.DataFrame({
        "row_ref": df["_row"],
        "date": dt_.dt.date,
        "shift": _shift(df["SHIFT"]),
        "vendor": text(df["LOCATION"]),
        "operator": text(df["OPERATOR"]),
        "unit": unit,
        "dn_no": text(df["DELIVERY NOTE"]),
        "liters": num(df["DELIVERY NOTE_VOLUME"]),
        "site": site.fillna(UNMAPPED),
    }).dropna(subset=["date"])
    out["month"] = month_start(out["date"])
    return out.reset_index(drop=True)
