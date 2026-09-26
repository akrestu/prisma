"""Kelola user: buat, ubah role & site, nonaktifkan, reset password, buka kunci."""
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
st.title("User & role")
all_sites = [x for x in sites_for(user) if x != UNMAPPED]

msg = st.session_state.pop("users_msg", None)
if msg:
    st.success(msg[0])
    if msg[1]:
        st.code(msg[1], language=None)
        st.caption("Password sementara hanya ditampilkan sekali. User wajib menggantinya saat login pertama.")

with st.expander("Tambah user", expanded=False):
    with st.form("add_user", clear_on_submit=True):
        a, b = st.columns(2)
        username = a.text_input("Username").strip().lower()
        name = b.text_input("Nama lengkap").strip()
        role = a.selectbox("Role", ROLES, format_func=ROLE_LABEL.get)
        email = b.text_input("Email (opsional)").strip()
        sites = st.multiselect("Site", all_sites)
        allsite = st.checkbox("Akses semua site (mis. management)")
        if st.form_submit_button("Buat user", type="primary"):
            if not username or not name:
                st.error("Isi username dan nama.")
            else:
                temp = secrets.token_urlsafe(9) + "7a"
                try:
                    with session_scope() as s:
                        security.create_user(s, username, name, role, temp, sites=sites,
                                             all_sites=allsite or role == "admin", email=email)
                        audit(s, user.username, "create_user", None, f"{username} ({role})")
                    st.session_state["users_msg"] = (f"User {username} dibuat.", temp)
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

with session_scope() as s:
    users = list(s.scalars(select(m.User).order_by(m.User.role, m.User.username)))
    links = pd.DataFrame(list(s.execute(select(m.UserSite.user_id, m.UserSite.site_code))),
                         columns=["user_id", "site"])
    rows = [(u.id, u.username, u.full_name, u.role, u.all_sites, u.active, security.is_locked(u), u.last_seen)
            for u in users]

st.subheader(f"{len(rows)} user")
for uid, uname, name, role, allsite, active, locked, seen in rows:
    own = links.loc[links["user_id"] == uid, "site"].tolist()
    badge = (":red-badge[terkunci]" if locked else "") + ("" if active else " :gray-badge[nonaktif]")
    with st.expander(f"**{uname}** · {name} · {ROLE_LABEL[role]} · "
                     f"{'semua site' if allsite else ', '.join(own) or 'tanpa site'} {badge}"):
        with st.form(f"edit_{uid}"):
            a, b = st.columns(2)
            new_role = a.selectbox("Role", ROLES, index=ROLES.index(role), format_func=ROLE_LABEL.get, key=f"r{uid}",
                                   disabled=uid == user.id)
            new_sites = b.multiselect("Site", all_sites, default=[x for x in own if x in all_sites], key=f"s{uid}")
            new_all = a.checkbox("Akses semua site", value=allsite, key=f"al{uid}")
            new_active = b.checkbox("Aktif", value=active, key=f"ac{uid}", disabled=uid == user.id)
            if st.form_submit_button("Simpan"):
                with session_scope() as s:
                    u = s.get(m.User, uid)
                    u.role, u.all_sites, u.active = new_role, new_all or new_role == "admin", new_active
                    s.execute(delete(m.UserSite).where(m.UserSite.user_id == uid))
                    for code in new_sites:
                        s.add(m.UserSite(user_id=uid, site_code=code))
                    audit(s, user.username, "update_user", None,
                          f"{uname}: role={new_role} sites={new_sites} all={new_all} aktif={new_active}")
                st.session_state["users_msg"] = (f"{uname} diperbarui.", None)
                st.rerun()
        c1, c2, _ = st.columns([1, 1, 3])
        if c1.button("Reset password", key=f"rp{uid}"):
            temp = secrets.token_urlsafe(9) + "7a"
            with session_scope() as s:
                security.set_password(s, uid, temp, must_change=True)
                audit(s, user.username, "reset_password", None, uname)
            st.session_state["users_msg"] = (f"Password {uname} direset.", temp)
            st.rerun()
        if locked and c2.button("Buka kunci", key=f"ul{uid}"):
            with session_scope() as s:
                u = s.get(m.User, uid)
                u.locked_until, u.failed_logins = None, 0
                audit(s, user.username, "unlock_user", None, uname)
            st.rerun()
