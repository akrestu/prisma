"""Validasi struktur file Eq.Event sebelum diproses."""
from __future__ import annotations

import pandas as pd

from core.io import frame

# sheet -> (baris header 0-based, kolom wajib)
SPEC: dict[str, tuple[int, list[str]]] = {
    "Populasi Unit": (0, ["Type", "Description", "Equipment", "Model", "Manufacturer", "Site"]),
    "Eq.Event": (0, ["Date", "Shift", "Unit ID", "Operator", "Jam Awal", "Jam Akhir", "Total Jam",
                     "HM awal", "HM Akhir", "Status", "Reason"]),
    "Ritasi Unit": (1, ["Date", "EqNumber", "EqModel", "Muatan", "Loader", "Loader Model", "Material",
                        "Lokasi Loader", "Disposal", "V Distance", "H Distance"]),
    "Data Timbangan": (0, ["Date", "No. ID.", "Nama Supplier", "Nama Product", "Tanggal / Jam Masuk",
                           "Tanggal / Jam Keluar", "Loader", "Shift", "Convert DT", "H Distance", "Tone",
                           "V Distance"]),
    "Fuel Consume": (0, ["DATE", "SHIFT", "MODEL", "UNIT", "TIME", "FLUID CONSUMPTION"]),
    "Fuel Receipt": (0, ["DATE_RECEIPT", "SHIFT", "LOCATION", "OPERATOR", "UNIT", "DELIVERY NOTE",
                         "DELIVERY NOTE_VOLUME"]),
}
HOUR_SLOTS = ["06-07", "07-08", "08-09", "09-10", "10-11", "11-12", "12-13", "13-14", "14-15", "15-16",
              "16-17", "17-18", "18-19", "19-20", "20-21", "21-22", "22-23", "23-00", "00-01", "01-02",
              "02-03", "03-04", "04-05", "05-06"]


class StructureError(ValueError):
    """File tidak sesuai format Eq.Event. `problems` berisi pesan per masalah."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Struktur file tidak sesuai:\n- " + "\n- ".join(problems))


def validate(raw: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Kembalikan frame per sheet (sudah ber-header) atau lempar StructureError."""
    problems, frames = [], {}
    for sheet, (hdr, cols) in SPEC.items():
        if sheet not in raw:
            problems.append(f"Sheet '{sheet}' tidak ditemukan.")
            continue
        if len(raw[sheet]) <= hdr:
            problems.append(f"Sheet '{sheet}' kosong.")
            continue
        df = frame(raw[sheet], hdr)
        need = cols + (HOUR_SLOTS if sheet == "Ritasi Unit" else [])
        missing = [c for c in need if c not in df.columns]
        if missing:
            where = f"baris {hdr + 1}"
            problems.append(f"Sheet '{sheet}' ({where}) tidak punya kolom: {', '.join(missing)}.")
        frames[sheet] = df
    if problems:
        raise StructureError(problems)
    return frames
