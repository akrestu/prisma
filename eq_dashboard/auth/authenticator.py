"""Login Streamlit: streamlit-authenticator (bcrypt + cookie JWT) dengan tabel users sebagai sumber kebenaran."""
from __future__ import annotations

import datetime as dt
import os

import streamlit as st
import streamlit_authenticator as stauth
from sqlalchemy import select
from streamlit_authenticator.utilities.exceptions import LoginError, LogoutError

from auth import security
from auth.access import CurrentUser, load_user
from db import models as m
from db.engine import session_scope

COOKIE_NAME = "eqdash_auth"
LOGIN_FIELDS = {"Form name": "Masuk", "Username": "Username", "Password": "Password", "Login": "Masuk"}


def _cookie_key() -> str:
    key = os.environ.get("AUTH_COOKIE_KEY")
    if not key:
        st.error("AUTH_COOKIE_KEY belum diset di environment.")
        st.stop()
    return key


def _on_login(info: dict) -> None:
    st.session_state["_fresh_login"] = True


def authenticate() -> tuple[CurrentUser | None, stauth.Authenticate]:
    with session_scope() as s:
        creds = security.credentials(s)
    auth = stauth.Authenticate(creds, COOKIE_NAME, _cookie_key(), cookie_expiry_days=1, auto_hash=False)
    try:
        auth.login(location="main", max_login_attempts=security.MAX_FAILED, fields=LOGIN_FIELDS,
                   callback=_on_login)
    except LoginError as e:
        st.error("Akun ini sedang dikunci atau tidak diizinkan masuk." if "attempts" in str(e) or
                 "authorized" in str(e) else str(e))
        _force_logout(auth)
        return None, auth

    with session_scope() as s:
        locked = security.sync_failed_attempts(s, creds)
    if locked:
        st.error(f"Terlalu banyak percobaan gagal. Akun dikunci {security.LOCK_MINUTES} menit.")
    status = st.session_state.get("authentication_status")
    if status is False and not locked:
        st.error("Username atau password salah.")
    if not status:
        return None, auth

    return _finish_login(st.session_state.get("username"), auth), auth


def _finish_login(username: str, auth: stauth.Authenticate) -> CurrentUser | None:
    fresh = st.session_state.pop("_fresh_login", False)
    with session_scope() as s:
        u = s.scalar(select(m.User).where(m.User.username == username, m.User.active))
        if u is None:
            _force_logout(auth)
            return None
        now = security.now()
        idle = u.last_seen is not None and now - u.last_seen > dt.timedelta(minutes=security.IDLE_MINUTES)
        if idle and not fresh and not st.session_state.get("_active"):
            s.add(m.AuditLog(username=username, action="session_expired"))
            _force_logout(auth)
            st.info(f"Sesi berakhir karena tidak aktif lebih dari {security.IDLE_MINUTES} menit. Silakan masuk lagi.")
            return None
        if fresh:
            s.add(m.AuditLog(username=username, action="login"))
        if u.last_seen is None or now - u.last_seen > dt.timedelta(seconds=60):
            u.last_seen = now
        st.session_state["_active"] = True
        return load_user(s, username)


def _force_logout(auth: stauth.Authenticate) -> None:
    try:
        auth.logout(location="unrendered")
    except LogoutError:
        pass
    st.session_state.pop("_active", None)
