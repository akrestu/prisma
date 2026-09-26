"""Perangkat Display (TV): token rahasia per TV, terkunci ke satu site. DB hanya menyimpan hash token."""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.security import now
from db import models as m

LAST_SEEN_EVERY = dt.timedelta(minutes=1)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_device(s: Session, name: str, site: str, created_by: int | None) -> tuple[m.DisplayDevice, str]:
    """Buat perangkat; token asli hanya dikembalikan sekali ini."""
    token = secrets.token_urlsafe(32)
    dev = m.DisplayDevice(name=name, site_code=site, token_hash=_hash(token), created_by=created_by)
    s.add(dev)
    s.flush()
    return dev, token


def regenerate(s: Session, dev: m.DisplayDevice) -> str:
    token = secrets.token_urlsafe(32)
    dev.token_hash, dev.active = _hash(token), True
    return token


def validate(s: Session, token: str | None) -> m.DisplayDevice | None:
    """Kembalikan perangkat aktif untuk token ini, dan catat last_seen (paling sering tiap menit)."""
    if not token or len(token) < 20:
        return None
    dev = s.scalar(select(m.DisplayDevice).where(m.DisplayDevice.token_hash == _hash(token),
                                                  m.DisplayDevice.active))
    if dev is None:
        return None
    t = now()
    if dev.last_seen is None or t - dev.last_seen > LAST_SEEN_EVERY:
        dev.last_seen = t
    return dev
