"""Konfigurasi aplikasi dari environment (.env saat lokal)."""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent
load_dotenv(APP_DIR / ".env")

UNMAPPED = "UNMAPPED"

# All sites run on WIB. Use these instead of date.today()/datetime.now(): a VPS clock is usually UTC,
# which would put the "current month" a day early between 00:00 and 07:00 WIB.
WIB = dt.timezone(dt.timedelta(hours=7), "WIB")


def now_wib() -> dt.datetime:
    return dt.datetime.now(WIB)


def today_wib() -> dt.date:
    return now_wib().date()

# Kategori jam kerja
READY, IDLE, STANDBY, DOWN, NO_DATA = "R", "I", "S", "D", "N"
STATUS_TO_CATEGORY = {"Operating": READY, "Idle": IDLE, "Standby": STANDBY, "SM": DOWN, "USM": DOWN}

# Standby yang disebabkan client (default; bisa diubah Admin lewat tabel standby_group)
DEFAULT_CLIENT_STANDBY = {325, 327}

# Hari dianggap lengkap bila >= 95% unit aktif punya data di kedua shift
COMPLETE_DAY_COVERAGE = 0.95


def database_url(test: bool = False) -> str:
    key = "TEST_DATABASE_URL" if test else "DATABASE_URL"
    url = os.environ.get(key)
    if not url:
        raise RuntimeError(f"{key} is not set. Copy .env.example to .env and fill it in.")
    return url
