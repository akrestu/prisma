"""Manage users: create, change role & sites, deactivate, reset password, unlock."""
import secrets

import pandas as pd
import streamlit as st
from sqlalchemy import delete, select

from auth import security
from auth.access import ROLE_LABEL, ROLES
from core.config import UNMAPPED
from core.ingest import audit
from core.ui import require, sites_for
from db import models as m
from db.engine import session_scope

user = require("users_roles")
st.title("Users & roles")
all_sites = [x for x in sites_for(user) if x != UNMAPPED]

msg = st.session_state.pop("users_msg", None)
if msg:
    st.success(msg[0])
    if msg[1]:
        st.code(msg[1], language=None)
        st.caption("The temporary password is shown only once. The user must change it at first sign-in.")

with st.expander("Add user", expanded=False), st.form("add_user", clear_on_submit=True):
    a, b = st.columns(2)
    username = a.text_input("Username").strip().lower()
    name = b.text_input("Full name").strip()
    role = a.selectbox("Role", ROLES, format_func=ROLE_LABEL.get)
    email = b.text_input("Email (optional)").strip()
    sites = st.multiselect("Sites", all_sites)
    allsite = st.checkbox("Access to all sites (e.g. management)")
    if st.form_submit_button("Create user", type="primary"):
        if not username or not name:
            st.error("Enter a username and a name.")
        else:
            temp = secrets.token_urlsafe(9) + "7a"
            try:
                with session_scope() as s:
                    security.create_user(s, username, name, role, temp, sites=sites,
                                         all_sites=allsite or role == "admin", email=email)
                    audit(s, user.username, "create_user", None, f"{username} ({role})")
                st.session_state["users_msg"] = (f"User {username} created.", temp)
                st.rerun()
            except ValueError as e:
                st.error(str(e))

with session_scope() as s:
    users = list(s.scalars(select(m.User).order_by(m.User.role, m.User.username)))
    links = pd.DataFrame(list(s.execute(select(m.UserSite.user_id, m.UserSite.site_code))),
                         columns=["user_id", "site"])
    rows = [(u.id, u.username, u.full_name, u.role, u.all_sites, u.active, security.is_locked(u)) for u in users]

st.subheader(f"{len(rows)} users")
for uid, uname, name, role, allsite, active, locked in rows:
    own = links.loc[links["user_id"] == uid, "site"].tolist()
    badge = (":orange-badge[locked]" if locked else "") + ("" if active else " :gray-badge[inactive]")
    with st.expander(f"**{uname}** · {name} · {ROLE_LABEL[role]} · "
                     f"{'all sites' if allsite else ', '.join(own) or 'no site'} {badge}"):
        with st.form(f"edit_{uid}"):
            a, b = st.columns(2)
            new_role = a.selectbox("Role", ROLES, index=ROLES.index(role), format_func=ROLE_LABEL.get, key=f"r{uid}",
                                   disabled=uid == user.id)
            new_sites = b.multiselect("Sites", all_sites, default=[x for x in own if x in all_sites], key=f"s{uid}")
            new_all = a.checkbox("Access to all sites", value=allsite, key=f"al{uid}")
            new_active = b.checkbox("Active", value=active, key=f"ac{uid}", disabled=uid == user.id)
            if st.form_submit_button("Save"):
                with session_scope() as s:
                    u = s.get(m.User, uid)
                    u.role, u.all_sites, u.active = new_role, new_all or new_role == "admin", new_active
                    # only the sites offered here are replaced: links to inactive sites stay
                    s.execute(delete(m.UserSite).where(m.UserSite.user_id == uid,
                                                       m.UserSite.site_code.in_(all_sites)))
                    for code in new_sites:
                        s.add(m.UserSite(user_id=uid, site_code=code))
                    audit(s, user.username, "update_user", None,
                          f"{uname}: role={new_role} sites={new_sites} all={new_all} active={new_active}")
                st.session_state["users_msg"] = (f"{uname} updated.", None)
                st.rerun()
        c1, c2, _ = st.columns([1, 1, 3])
        if c1.button("Reset password", key=f"rp{uid}"):
            temp = secrets.token_urlsafe(9) + "7a"
            with session_scope() as s:
                security.set_password(s, uid, temp, must_change=True)
                audit(s, user.username, "reset_password", None, uname)
            st.session_state["users_msg"] = (f"Password of {uname} reset.", temp)
            st.rerun()
        if locked and c2.button("Unlock", key=f"ul{uid}"):
            with session_scope() as s:
                u = s.get(m.User, uid)
                u.locked_until, u.failed_logins = None, 0
                audit(s, user.username, "unlock_user", None, uname)
            st.rerun()
