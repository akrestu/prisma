"""Reading Data_Prod workbooks (.xlsb or .xlsx) without Excel, via the calamine engine."""
from __future__ import annotations

import datetime as dt
import hashlib
import io
from pathlib import Path
from typing import BinaryIO

import pandas as pd

EXCEL_EPOCH = "1899-12-30"


def file_bytes(source: str | Path | bytes | BinaryIO) -> bytes:
    if isinstance(source, bytes):
        return source
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    return source.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_workbook(data: bytes, engine: str = "calamine") -> dict[str, pd.DataFrame]:
    """All sheets as raw frames (header=None) in one read. calamine reads .xlsb and .xlsx alike, ~8x faster than
    pyxlsb (deprecated in pandas 3.1) and returns real dates/times instead of Excel serial numbers."""
    return pd.read_excel(io.BytesIO(data), engine=engine, sheet_name=None, header=None)


def frame(raw: pd.DataFrame, header_row: int) -> pd.DataFrame:
    """Jadikan baris `header_row` sebagai nama kolom. Nama ganda diberi akhiran .1, .2 (mis. 'Model.1')."""
    names, seen = [], {}
    for i, v in enumerate(raw.iloc[header_row].tolist()):
        name = str(v).strip() if pd.notna(v) and str(v).strip() else f"_col{i}"
        if name in seen:
            seen[name] += 1
            name = f"{name}.{seen[name]}"
        else:
            seen[name] = 0
        names.append(name)
    df = raw.iloc[header_row + 1:].copy()
    df.columns = names
    return df.dropna(how="all").reset_index(drop=True)


def excel_date(s: pd.Series) -> pd.Series:
    """Dates/datetimes from any reader: real datetimes (calamine), Excel serial numbers (pyxlsb) or text."""
    serial = pd.to_numeric(s, errors="coerce")
    out = pd.to_datetime(serial, unit="D", origin=EXCEL_EPOCH)
    rest = serial.isna() & s.notna()
    if rest.any():
        other = pd.to_datetime(s.where(rest).map(lambda v: v if isinstance(v, (dt.datetime, dt.date)) or pd.isna(v)
                                                 else str(v)), errors="coerce", format="mixed")
        out = out.where(~rest, other)
    return out


def day_fraction(s: pd.Series) -> pd.Series:
    """Time of day as a fraction of a day (06:00 → 0.25): accepts datetime.time, datetime, serial numbers or 'HH:MM'."""
    def one(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return float("nan")
        if isinstance(v, dt.datetime):
            v = v.time()
        if isinstance(v, dt.time):
            return (v.hour * 3600 + v.minute * 60 + v.second + v.microsecond / 1e6) / 86400
        if isinstance(v, (int, float)):
            return float(v) % 1.0 if v >= 1 else float(v)
        try:
            t = pd.to_datetime(str(v), format="mixed").time()
            return (t.hour * 3600 + t.minute * 60 + t.second) / 86400
        except (ValueError, TypeError):
            return float("nan")
    return s.map(one).astype(float)


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def text(s: pd.Series) -> pd.Series:
    """String rapi: strip spasi, kosong → NA."""
    out = s.astype("string").str.strip()
    return out.mask(out == "")
