"""Engine & session SQLAlchemy. Layer Streamlit membungkus get_engine dengan st.cache_resource."""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import database_url


@lru_cache(maxsize=4)
def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), pool_pre_ping=True, insertmanyvalues_page_size=1000)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Satu transaksi: commit bila sukses, rollback bila gagal."""
    factory = sessionmaker(bind=engine or get_engine(), expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
