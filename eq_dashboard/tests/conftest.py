from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

SAMPLE = APP_DIR.parent / "Eq.Event.xlsb"
TARGET = APP_DIR.parent / "Target.xlsx"
needs_sample = pytest.mark.skipif(not SAMPLE.exists(), reason="sample Eq.Event.xlsb not found")


@pytest.fixture(scope="session")
def sample_bytes() -> bytes:
    if not SAMPLE.exists():
        pytest.skip("sample Eq.Event.xlsb not found")
    return SAMPLE.read_bytes()


@pytest.fixture(scope="session")
def parsed(sample_bytes):
    from core.parse import parse_eq_event
    return parse_eq_event(sample_bytes)


@pytest.fixture(scope="session")
def raw_frames(sample_bytes):
    from core.io import read_workbook
    return read_workbook(sample_bytes)


@pytest.fixture(scope="session")
def test_engine():
    """The test database with the current schema, built once per test run."""
    from core.config import database_url
    from db.engine import get_engine
    from db.models import Base

    try:
        engine = get_engine(database_url(test=True))
        with engine.connect():
            pass
    except Exception as e:  # pragma: no cover
        pytest.skip(f"test database not available: {e}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def db_session(test_engine):
    """An empty test database for every test: one TRUNCATE instead of dropping and creating every table. Pages run
    with AppTest use their own connections, so the data is committed for real (no rollback-only transaction)."""
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from db.models import Base

    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with test_engine.begin() as c:
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    s = sessionmaker(bind=test_engine, expire_on_commit=False)()
    yield s
    s.rollback()
    s.close()
