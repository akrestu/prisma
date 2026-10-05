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
# short codes typed on a TV remote: no 0/O, 1/I/L. 8 of 31 symbols ≈ 8.5e11 codes, plus the failure limit below
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LEN = 8
FAIL_LIMIT, FAIL_WINDOW = 20, dt.timedelta(minutes=10)
_fails: dict[str, list[dt.datetime]] = {}


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))


def normalize(code: str | None) -> str | None:
    """'k7m2-qx9p' / 'K7M2 QX9P' → 'K7M2QX9P'; None when it cannot be a TV code (old long links included)."""
    if not code:
        return None
    c = "".join(ch for ch in str(code).upper() if ch.isalnum())
    return c if len(c) == CODE_LEN and all(ch in ALPHABET for ch in c) else None


def pretty(code: str) -> str:
    """'K7M2QX9P' → 'K7M2-QX9P' (easier to read and type)."""
    return f"{code[:4]}-{code[4:]}"


def blocked(client: str | None) -> bool:
    """True after FAIL_LIMIT wrong codes from one client within FAIL_WINDOW: guessing codes is not worth it."""
    t = now()
    recent = [x for x in _fails.get(client or "?", []) if t - x < FAIL_WINDOW]
    _fails[client or "?"] = recent
    return len(recent) >= FAIL_LIMIT


def record_failure(client: str | None) -> None:
    _fails.setdefault(client or "?", []).append(now())


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
    return token if _hash(token) == dev.token_hash and normalize(token) == token else None


def create_device(s: Session, name: str, site: str, created_by: int | None) -> tuple[m.DisplayDevice, str]:
    """Buat perangkat dengan kode pendek baru (dikembalikan; disimpan sebagai hash + terenkripsi)."""
    token = _unique_code(s)
    dev = m.DisplayDevice(name=name, site_code=site, token_hash=_hash(token), token_enc=_seal(token),
                          created_by=created_by)
    s.add(dev)
    s.flush()
    return dev, token


def _unique_code(s: Session) -> str:
    while True:   # a clash is practically impossible, but the hash column is unique
        code = new_code()
        if s.scalar(select(m.DisplayDevice.id).where(m.DisplayDevice.token_hash == _hash(code))) is None:
            return code


def regenerate(s: Session, dev: m.DisplayDevice) -> str:
    token = _unique_code(s)
    dev.token_hash, dev.token_enc, dev.active = _hash(token), _seal(token), True
    return token


def validate(s: Session, token: str | None) -> m.DisplayDevice | None:
    """Kembalikan perangkat aktif untuk kode ini, dan catat last_seen (paling sering tiap menit). Old long tokens
    are no longer accepted: every TV uses a short code."""
    token = normalize(token)
    if token is None:
        return None
    dev = s.scalar(select(m.DisplayDevice).where(m.DisplayDevice.token_hash == _hash(token),
                                                  m.DisplayDevice.active))
    if dev is None:
        return None
    t = now()
    if dev.last_seen is None or t - dev.last_seen > LAST_SEEN_EVERY:
        dev.last_seen = t
    return dev
