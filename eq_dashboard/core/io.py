"""Membaca file Eq.Event.xlsb tanpa Excel (pyxlsb)."""
from __future__ import annotations

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


def read_workbook(data: bytes, engine: str = "pyxlsb") -> dict[str, pd.DataFrame]:
    """Semua sheet sebagai frame mentah (header=None) dalam satu kali baca."""
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
    """pyxlsb mengembalikan tanggal sebagai angka serial Excel → datetime."""
    return pd.to_datetime(pd.to_numeric(s, errors="coerce"), unit="D", origin=EXCEL_EPOCH)


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def text(s: pd.Series) -> pd.Series:
    """String rapi: strip spasi, kosong → NA."""
    out = s.astype("string").str.strip()
    return out.mask(out == "")
