"""Password (bcrypt), kebijakan password, lockout. Bebas dari Streamlit agar mudah dites."""
from __future__ import annotations

import datetime as dt

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import models as m

MIN_PASSWORD = 10
MAX_FAILED = 5
LOCK_MINUTES = 15
IDLE_MINUTES = 60


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def password_problem(pw: str, username: str = "") -> str | None:
    if len(pw) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters."
    if username and username.lower() in pw.lower():
        return "Password must not contain the username."
    if pw.isdigit() or pw.isalpha():
        return "Password must mix letters with numbers or symbols."
    return None


def is_locked(u: m.User) -> bool:
    return u.locked_until is not None and u.locked_until > now()


def credentials(s: Session) -> dict:
    """Format credentials streamlit-authenticator. User nonaktif / terkunci tidak dimasukkan
    sehingga login maupun cookie lama mereka ditolak."""
    users = {}
    for u in s.scalars(select(m.User).where(m.User.active)):
        if is_locked(u):
            continue
        first, _, last = u.full_name.partition(" ")
        users[u.username] = {"email": u.email or f"{u.username}@local", "first_name": first, "last_name": last,
                             "password": u.password_hash, "roles": [u.role],
                             "failed_login_attempts": u.failed_logins, "logged_in": False}
    return {"usernames": users}


def sync_failed_attempts(s: Session, creds: dict) -> list[str]:
    """Tulis balik hitungan gagal login dari credentials ke DB; kunci akun yang mencapai batas.
    Mengembalikan username yang baru terkunci."""
    locked = []
    for username, info in creds["usernames"].items():
        u = s.scalar(select(m.User).where(m.User.username == username))
        n = int(info.get("failed_login_attempts", 0))
        if u is None or n == u.failed_logins:
            continue
        if n >= MAX_FAILED:
            u.failed_logins, u.locked_until = 0, now() + dt.timedelta(minutes=LOCK_MINUTES)
            s.add(m.AuditLog(username=username, action="account_locked",
                             detail=f"{MAX_FAILED} failed logins, locked for {LOCK_MINUTES} minutes"))
            locked.append(username)
        else:
            u.failed_logins = n
            s.add(m.AuditLog(username=username, action="login_failed", detail=f"attempt {n}"))
    return locked


def create_user(s: Session, username: str, full_name: str, role: str, password: str,
                sites: list[str] | None = None, all_sites: bool = False, email: str = "",
                must_change_password: bool = True) -> m.User:
    problem = password_problem(password, username)
    if problem:
        raise ValueError(problem)
    if s.scalar(select(m.User.id).where(m.User.username == username)):
        raise ValueError(f"Username '{username}' is already taken.")
    u = m.User(username=username, full_name=full_name, role=role, email=email,
               password_hash=hash_password(password), all_sites=all_sites,
               must_change_password=must_change_password)
    s.add(u)
    s.flush()
    for code in sites or []:
        if s.get(m.Site, code) is None:
            s.add(m.Site(code=code, name=code))
            s.flush()
        s.add(m.UserSite(user_id=u.id, site_code=code))
    return u


def set_password(s: Session, user_id: int, new_pw: str, must_change: bool = False) -> None:
    u = s.get(m.User, user_id)
    problem = password_problem(new_pw, u.username)
    if problem:
        raise ValueError(problem)
    u.password_hash, u.must_change_password = hash_password(new_pw), must_change
    u.failed_logins, u.locked_until = 0, None
