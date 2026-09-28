"""Login Streamlit: streamlit-authenticator (bcrypt + cookie JWT) dengan tabel users sebagai sumber kebenaran."""
from __future__ import annotations

import contextlib
import datetime as dt
import os

import streamlit as st
import streamlit_authenticator as stauth
from sqlalchemy import select
from streamlit_authenticator.utilities.exceptions import LoginError, LogoutError

from auth import security
from auth.access import CurrentUser, load_user
from core import brand
from db import models as m
from db.engine import session_scope

COOKIE_NAME = "eqdash_auth"
LOGIN_FIELDS = {"Form name": "Sign in to PRISMA", "Username": "Username", "Password": "Password", "Login": "Sign in"}


def _cookie_key() -> str:
    key = os.environ.get("AUTH_COOKIE_KEY", "")
    # it signs the login cookie: a short or example key would let anyone forge a session
    if len(key) < 32 or key.startswith("CHANGE_ME"):
        st.error("AUTH_COOKIE_KEY must be a random secret of at least 32 characters "
                 "(python -c \"import secrets; print(secrets.token_urlsafe(48))\").")
        st.stop()
    return key


def _on_login(info: dict) -> None:
    st.session_state["_fresh_login"] = True


def authenticate() -> tuple[CurrentUser | None, stauth.Authenticate]:
    with session_scope() as s:
        creds = security.credentials(s)
    auth = stauth.Authenticate(creds, COOKIE_NAME, _cookie_key(), cookie_expiry_days=1, auto_hash=False)
    if st.session_state.get("authentication_status"):
        # already signed in this session: no sign-in layout at all
        auth.login(location="unrendered", max_login_attempts=security.MAX_FAILED, callback=_on_login)
        return _finish_login(st.session_state.get("username"), auth), auth

    with st.container(key="login_shell"):
        brand_col, form_col = st.columns([1.05, 1])
        with form_col:
            user = _login_form(auth, creds)
        if user is None:
            st.html(brand.LOGIN_CSS)
            with brand_col:
                brand.brand_panel()
            with form_col:
                brand.login_help()
    if user is not None:
        # hide, don't empty: the cookie component rendered inside the form must stay mounted
        # long enough to write the re-auth cookie, otherwise every browser refresh logs out
        st.html("<style>.st-key-login_shell{display:none}</style>")
    return user, auth


def _login_form(auth: stauth.Authenticate, creds: dict) -> CurrentUser | None:
    try:
        auth.login(location="main", max_login_attempts=security.MAX_FAILED, fields=LOGIN_FIELDS,
                   callback=_on_login)
    except LoginError as e:
        st.error("This account is locked or not allowed to sign in." if "attempts" in str(e) or
                 "authorized" in str(e) else str(e))
        _force_logout(auth)
        return None

    with session_scope() as s:
        locked = security.sync_failed_attempts(s, creds)
    if locked:
        st.error(f"Too many failed attempts. The account is locked for {security.LOCK_MINUTES} minutes.")
    status = st.session_state.get("authentication_status")
    if status is False and not locked:
        st.error("Incorrect username or password.")
    if not status:
        return None
    return _finish_login(st.session_state.get("username"), auth)


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
            st.info(f"Your session ended after more than {security.IDLE_MINUTES} minutes of inactivity. Please sign in again.")
            return None
        if fresh:
            s.add(m.AuditLog(username=username, action="login"))
        if u.last_seen is None or now - u.last_seen > dt.timedelta(seconds=60):
            u.last_seen = now
        st.session_state["_active"] = True
        return load_user(s, username)


def _force_logout(auth: stauth.Authenticate) -> None:
    with contextlib.suppress(LogoutError):
        auth.logout(location="unrendered")
    st.session_state.pop("_active", None)
