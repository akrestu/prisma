"""App entrypoint: login → role-based navigation. `?display=<token>` opens the TV screen (kiosk)."""
import streamlit as st

from core import brand  # noqa: E402  (no Streamlit calls at import)

st.set_page_config(page_title=brand.NAME, page_icon=brand.FAVICON, layout="wide")

from auth.access import PAGE_ROLES, ROLE_LABEL  # noqa: E402
from auth.authenticator import authenticate  # noqa: E402
from db import repo  # noqa: E402
from db.engine import session_scope  # noqa: E402

if "display" in st.query_params:
    # Kiosk TV mode: no login, token locked to one site, TV screen only.
    from auth.display import validate
    from pages.tv.screen import show

    with session_scope() as s:
        dev = validate(s, st.query_params.get("display"))
        site = dev.site_code if dev else None
    if site is None:
        st.error("This TV link is invalid or has been revoked. Contact your Admin.")
        st.stop()

    @st.fragment(run_every="5m")
    def tv_screen():
        # token and period are re-read on every refresh: revocation / period change apply within 5 minutes
        with session_scope() as s:
            d = validate(s, st.query_params.get("display"))
            period = d.period if d else None
        if period is None:
            st.error("This TV link has been revoked.")
            return
        show(site, kiosk=True, period=period)

    st.navigation([st.Page(tv_screen, title=f"TV {site}", url_path="tv")], position="hidden").run()
    st.stop()

user, auth = authenticate()
if user is None:
    st.session_state.pop("user", None)
    st.navigation([st.Page(lambda: None, title=f"Sign in · {brand.NAME}", url_path="login")], position="hidden").run()
    st.stop()
st.session_state["user"] = user


def P(path, title, icon, **kw):
    return st.Page(path, title=title, icon=f":material/{icon}:", **kw)


DASH = {
    "overview": P("pages/dashboard/overview.py", "Overview", "dashboard", default=True),
    "pa_ua": P("pages/dashboard/pa_ua.py", "PA & UoA", "speed"),
    "time_distribution": P("pages/dashboard/time_distribution.py", "Time distribution", "donut_large"),
    "reliability": P("pages/dashboard/reliability.py", "Reliability", "build"),
    "production_ob": P("pages/dashboard/production_ob.py", "OB production", "landscape"),
    "coal_getting": P("pages/dashboard/coal_getting.py", "Coal getting", "local_shipping"),
    "loader_fleet": P("pages/dashboard/loader_fleet.py", "Loader & hauler productivity", "construction"),
    "fuel": P("pages/dashboard/fuel.py", "Fuel", "local_gas_station"),
    "data_quality": P("pages/dashboard/data_quality.py", "Data quality", "rule"),
}
OTHER = {
    "preview_tv": P("pages/tv/preview.py", "TV preview", "tv"),
    "upload": P("pages/data/upload.py", "Upload data", "upload_file"),
    "approval": P("pages/data/approval.py", "Approval", "fact_check"),
    "upload_history": P("pages/data/upload_history.py", "Upload history", "history"),
    "users_roles": P("pages/admin/users_roles.py", "Users & roles", "group"),
    "targets_plan": P("pages/admin/targets_plan.py", "Targets & plan", "flag"),
    "pm_interval": P("pages/admin/pm_interval.py", "PM intervals & standby", "schedule"),
    "sites_mapping": P("pages/admin/sites_mapping.py", "Sites & mapping", "account_tree"),
    "display_devices": P("pages/admin/display_devices.py", "TV devices", "cast"),
    "audit_log": P("pages/admin/audit_log.py", "Audit log", "receipt_long"),
    "home": P("pages/home.py", "Data status", "info"),
    "account": P("pages/account.py", "Change password", "key"),
}


def allowed(key: str) -> bool:
    return user.role in PAGE_ROLES[key]


if user.must_change_password:
    nav = st.navigation([OTHER["account"]])
else:
    if allowed("approval"):
        from core.ui import sites_for

        with session_scope() as s:
            n = repo.pending_count(s, sites_for(user))
        if n:
            OTHER["approval"] = P("pages/data/approval.py", f"Approval ({n})", "fact_check")
    pick = lambda keys, src=OTHER: [src[k] for k in keys if allowed(k)]  # noqa: E731
    sections = {
        "Dashboard": pick(DASH, DASH),
        "TV screen": pick(["preview_tv"]),
        "Data": pick(["upload", "approval", "upload_history"]),
        "Admin": pick(["users_roles", "targets_plan", "pm_interval", "sites_mapping", "display_devices", "audit_log"]),
        "Account": pick(["home", "account"]),
    }
    nav = st.navigation({k: v for k, v in sections.items() if v})

brand.sidebar_logo()
with st.sidebar:
    st.markdown(f"**{user.name}**  \n{ROLE_LABEL[user.role]}")
    auth.logout("Sign out", location="sidebar", key="logout_btn",
                callback=lambda _info: st.session_state.pop("user", None))

nav.run()
