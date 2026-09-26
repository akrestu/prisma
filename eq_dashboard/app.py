"""Entrypoint aplikasi: login → navigasi sesuai role. `?display=<token>` membuka layar TV (kiosk)."""
import streamlit as st

st.set_page_config(page_title="Eq Dashboard", page_icon=":material/monitoring:", layout="wide")

from auth.access import PAGE_ROLES, ROLE_LABEL  # noqa: E402
from auth.authenticator import authenticate  # noqa: E402
from db import repo  # noqa: E402
from db.engine import session_scope  # noqa: E402

if "display" in st.query_params:
    # Mode kiosk TV: tanpa login, token terkunci ke satu site, hanya layar TV.
    from auth.display import validate
    from pages.tv.screen import show

    with session_scope() as s:
        dev = validate(s, st.query_params.get("display"))
        site = dev.site_code if dev else None
    if site is None:
        st.error("Link TV tidak valid atau sudah dicabut. Hubungi Admin.")
        st.stop()

    @st.fragment(run_every="5m")
    def tv_screen():
        with session_scope() as s:  # token dicek ulang tiap refresh: pencabutan berlaku ≤ 5 menit
            ok = validate(s, st.query_params.get("display")) is not None
        if not ok:
            st.error("Link TV sudah dicabut.")
            return
        show(site, kiosk=True)

    st.navigation([st.Page(tv_screen, title=f"TV {site}", url_path="tv")], position="hidden").run()
    st.stop()

user, auth = authenticate()
if user is None:
    st.session_state.pop("user", None)
    st.navigation([st.Page(lambda: None, title="Masuk", url_path="login")], position="hidden").run()
    st.stop()
st.session_state["user"] = user

PAGES = {
    "home": st.Page("pages/home.py", title="Beranda", icon=":material/home:", default=True),
    "upload": st.Page("pages/data/upload.py", title="Upload data", icon=":material/upload_file:"),
    "approval": st.Page("pages/data/approval.py", title="Approval", icon=":material/fact_check:"),
    "upload_history": st.Page("pages/data/upload_history.py", title="Riwayat upload", icon=":material/history:"),
    "account": st.Page("pages/account.py", title="Ganti password", icon=":material/key:"),
    "preview_tv": st.Page("pages/tv/preview.py", title="Preview TV", icon=":material/tv:"),
    "display_devices": st.Page("pages/admin/display_devices.py", title="Perangkat TV", icon=":material/cast:"),
}


def allowed(key: str) -> bool:
    return user.role in PAGE_ROLES[key]


if user.must_change_password:
    nav = st.navigation([PAGES["account"]])
else:
    if allowed("approval"):
        from core.ui import sites_for

        with session_scope() as s:
            n = repo.pending_count(s, sites_for(user))
        if n:
            PAGES["approval"] = st.Page("pages/data/approval.py", title=f"Approval ({n})",
                                        icon=":material/fact_check:")
    sections = {
        "": [PAGES["home"]] + ([PAGES["preview_tv"]] if allowed("preview_tv") else []),
        "Data": [PAGES[k] for k in ("upload", "approval", "upload_history") if allowed(k)],
        "Admin": [PAGES[k] for k in ("display_devices",) if allowed(k)],
        "Akun": [PAGES["account"]],
    }
    nav = st.navigation({k: v for k, v in sections.items() if v})

with st.sidebar:
    st.markdown(f"**{user.name}**  \n{ROLE_LABEL[user.role]}")
    auth.logout("Keluar", location="sidebar", key="logout_btn",
                callback=lambda _info: st.session_state.pop("user", None))

nav.run()
