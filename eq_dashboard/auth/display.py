"""Perangkat Display (TV): token rahasia per TV, terkunci ke satu site.

Lookup uses a hash: HMAC keyed by TV_CODE_KEY when it is set, so a short code cannot be brute-forced from a copy of the
database alone (plain SHA-256 otherwise). Rows with the plain hash are upgraded on their next successful lookup. The
token is also kept encrypted with a key derived from AUTH_COOKIE_KEY, so an Admin can copy a TV's link again later."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import os
import secrets
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.security import now
from db import models as m

LAST_SEEN_EVERY = dt.timedelta(minutes=1)
# short codes typed on a TV remote: no 0/O, 1/I/L. 8 of 31 symbols ≈ 8.5e11 codes, plus the failure limit below
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LEN = 8
FAIL_LIMIT, FAIL_WINDOW = 20, dt.timedelta(minutes=10)
MAX_CLIENTS = 10_000   # memory cap for the failure table
_fails: dict[str, list[dt.datetime]] = {}
_fails_lock = threading.Lock()


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


def client_ip(headers, peer: str | None) -> str | None:
    """The visitor's IP behind the reverse proxy (Coolify/Traefik). The right-most X-Forwarded-For entry is the one the
    proxy itself appended, so a client cannot forge it. Without the header, the TCP peer."""
    xff = (headers or {}).get("X-Forwarded-For") or ""
    hops = [h.strip() for h in xff.split(",") if h.strip()]
    return hops[-1] if hops else peer


def _prune(t: dt.datetime) -> None:
    """Drop clients without a recent failure; if still too many, drop the oldest. Caller holds the lock."""
    for k in [k for k, v in _fails.items() if not v or t - v[-1] >= FAIL_WINDOW]:
        del _fails[k]
    if len(_fails) > MAX_CLIENTS:
        for k in sorted(_fails, key=lambda k: _fails[k][-1])[:len(_fails) - MAX_CLIENTS]:
            del _fails[k]


def blocked(client: str | None) -> bool:
    """True after FAIL_LIMIT wrong codes from one client within FAIL_WINDOW: guessing codes is not worth it."""
    t, key = now(), client or "?"
    with _fails_lock:
        recent = [x for x in _fails.get(key, []) if t - x < FAIL_WINDOW]
        if recent:
            _fails[key] = recent
        else:
            _fails.pop(key, None)
        return len(recent) >= FAIL_LIMIT


def record_failure(client: str | None) -> None:
    t = now()
    with _fails_lock:
        _fails.setdefault(client or "?", []).append(t)
        if len(_fails) > MAX_CLIENTS:
            _prune(t)


def _legacy_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _hash(token: str) -> str:
    """HMAC-SHA256 keyed by TV_CODE_KEY (its own secret, so rotating AUTH_COOKIE_KEY does not break TVs); plain SHA-256
    without it. Changing TV_CODE_KEY later invalidates every TV code: regenerate the links."""
    secret = os.environ.get("TV_CODE_KEY", "")
    if len(secret) < 32:
        return _legacy_hash(token)
    key = hashlib.sha256(b"prisma-tv-hash|" + secret.encode()).digest()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


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
    return token if dev.token_hash in (_hash(token), _legacy_hash(token)) and normalize(token) == token else None


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
        if s.scalar(select(m.DisplayDevice.id).where(
                m.DisplayDevice.token_hash.in_({_hash(code), _legacy_hash(code)}))) is None:
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
    keyed = _hash(token)
    dev = s.scalar(select(m.DisplayDevice).where(m.DisplayDevice.token_hash.in_({keyed, _legacy_hash(token)}),
                                                  m.DisplayDevice.active))
    if dev is None:
        return None
    if dev.token_hash != keyed:   # hashed before keyed hashing: upgrade in place
        dev.token_hash = keyed
    t = now()
    if dev.last_seen is None or t - dev.last_seen > LAST_SEEN_EVERY:
        dev.last_seen = t
    return dev
