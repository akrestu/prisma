"""Ganti password. Juga dipakai sebagai halaman wajib saat login pertama."""
import streamlit as st

from auth import security
from core.ui import require
from db import models as m
from db.engine import session_scope

user = require("account")
st.title("Ganti password")
if user.must_change_password:
    st.warning("Ini login pertama Anda. Ganti password sebelum melanjutkan.")

with st.form("change_pw", clear_on_submit=True):
    old = st.text_input("Password lama", type="password")
    new = st.text_input(f"Password baru (minimal {security.MIN_PASSWORD} karakter, campuran huruf dan angka)",
                        type="password")
    rep = st.text_input("Ulangi password baru", type="password")
    ok = st.form_submit_button("Simpan", type="primary")

if ok:
    with session_scope() as s:
        u = s.get(m.User, user.id)
        if not security.check_password(old, u.password_hash):
            st.error("Password lama salah.")
        elif new != rep:
            st.error("Ulangan password baru tidak sama.")
        elif new == old:
            st.error("Password baru harus berbeda dari yang lama.")
        else:
            try:
                security.set_password(s, user.id, new)
                s.add(m.AuditLog(username=user.username, action="password_changed"))
                st.session_state["user"] = type(user)(**{**user.__dict__, "must_change_password": False})
                st.success("Password diperbarui.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
