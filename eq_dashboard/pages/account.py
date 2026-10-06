"""Change password. Also the mandatory page on first sign-in."""
import streamlit as st

from auth import security
from core.ui import require
from db import models as m
from db.engine import session_scope

user = require("account")
st.title("Change password")
if user.must_change_password:
    st.warning("This is your first sign-in. Change your password to continue.")

with st.form("change_pw", clear_on_submit=True):
    old = st.text_input("Current password", type="password")
    new = st.text_input(f"New password (at least {security.MIN_PASSWORD} characters, letters and numbers)",
                        type="password")
    rep = st.text_input("Repeat new password", type="password")
    ok = st.form_submit_button("Save", type="primary")

if ok:
    changed = False
    with session_scope() as s:
        u = s.get(m.User, user.id)
        if not security.check_password(old, u.password_hash):
            st.error("Current password is incorrect.")
        elif new != rep:
            st.error("The new passwords do not match.")
        elif new == old:
            st.error("The new password must differ from the current one.")
        else:
            try:
                security.set_password(s, user.id, new)
                s.add(m.AuditLog(username=user.username, action="password_changed"))
                st.session_state["user"] = type(user)(**{**user.__dict__, "must_change_password": False})
                changed = True
            except ValueError as e:
                st.error(str(e))
    # st.rerun() raises a BaseException: calling it inside session_scope skips the commit.
    if changed:
        st.session_state["password_updated"] = True
        st.rerun()
