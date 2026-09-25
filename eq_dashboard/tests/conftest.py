from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

SAMPLE = APP_DIR.parent / "Eq.Event.xlsb"
TARGET = APP_DIR.parent / "Target.xlsx"
needs_sample = pytest.mark.skipif(not SAMPLE.exists(), reason="Eq.Event.xlsb contoh tidak ada")


@pytest.fixture(scope="session")
def sample_bytes() -> bytes:
    if not SAMPLE.exists():
        pytest.skip("Eq.Event.xlsb contoh tidak ada")
    return SAMPLE.read_bytes()


@pytest.fixture(scope="session")
def parsed(sample_bytes):
    from core.parse import parse_eq_event
    return parse_eq_event(sample_bytes)


@pytest.fixture(scope="session")
def raw_frames(sample_bytes):
    from core.io import read_workbook
    return read_workbook(sample_bytes)


@pytest.fixture()
def db_session():
    """Database test bersih untuk setiap test."""
    from sqlalchemy.orm import sessionmaker

    from core.config import database_url
    from db.engine import get_engine
    from db.models import Base

    try:
        engine = get_engine(database_url(test=True))
        with engine.connect():
            pass
    except Exception as e:  # pragma: no cover
        pytest.skip(f"database test tidak tersedia: {e}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.rollback()
    s.close()
