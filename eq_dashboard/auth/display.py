"""Perangkat Display (TV): token rahasia per TV, terkunci ke satu site.

Lookup uses the hash only. The token is also kept encrypted with a key derived from AUTH_COOKIE_KEY, so an Admin can
copy a TV's link again later; a copy of the database without that secret cannot reveal any link."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import os
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.security import now
from db import models as m

LAST_SEEN_EVERY = dt.timedelta(minutes=1)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fernet():
    """Cipher from the app secret (its own derivation, not the cookie key itself). None without a usable secret."""
    from cryptography.fernet import Fernet
    secret = os.environ.get("AUTH_COOKIE_KEY", "")
    if len(secret) < 32:
        return None
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"prisma-tv-link|" + secret.encode()).digest()))


def _seal(token: str) -> str | None:
    f = _fernet()
    return f.encrypt(token.encode()).decode() if f else None


def token_of(dev: m.DisplayDevice) -> str | None:
    """The TV's token for 'Copy link', or None (made before links were stored, or the app secret changed)."""
    from cryptography.fernet import InvalidToken
    f = _fernet()
    if not (f and dev.token_enc):
        return None
    try:
        token = f.decrypt(dev.token_enc.encode()).decode()
    except InvalidToken:
        return None
    return token if _hash(token) == dev.token_hash else None


def create_device(s: Session, name: str, site: str, created_by: int | None) -> tuple[m.DisplayDevice, str]:
    """Buat perangkat; token asli hanya dikembalikan sekali ini."""
    token = secrets.token_urlsafe(32)
    dev = m.DisplayDevice(name=name, site_code=site, token_hash=_hash(token), token_enc=_seal(token),
                          created_by=created_by)
    s.add(dev)
    s.flush()
    return dev, token


def regenerate(s: Session, dev: m.DisplayDevice) -> str:
    token = secrets.token_urlsafe(32)
    dev.token_hash, dev.token_enc, dev.active = _hash(token), _seal(token), True
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
