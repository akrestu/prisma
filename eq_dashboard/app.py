"""App entrypoint: login → role-based navigation. `?tv=<code>` opens the TV screen (kiosk)."""
import streamlit as st

from core import brand
from core import theme as T
from core.validate import PRODUCTION_DATA, UNIT_POPULATION

st.set_page_config(page_title=brand.NAME, page_icon=brand.FAVICON, layout="wide")

from auth.access import DATA_OFFICER, PAGE_ROLES, ROLE_LABEL, SITE_MANAGER  # noqa: E402
from auth.authenticator import authenticate  # noqa: E402
from db import repo  # noqa: E402
from db.engine import session_scope  # noqa: E402

if "display" in st.query_params:   # the old long links: replaced by short codes
    st.error("This TV link is no longer used. Ask your Admin for the new short TV link (…/?tv=XXXX-XXXX).")
    st.stop()

if "tv" in st.query_params:
    # Kiosk TV mode: no login, code locked to one site, TV screen only.
    from auth.display import blocked, client_ip, record_failure, validate
    from pages.tv.screen import show, show_hourly

    client = client_ip(st.context.headers, st.context.ip_address)
    if blocked(client):
        st.error("Too many wrong TV codes. Wait 10 minutes and check the code with your Admin.")
        st.stop()
    with session_scope() as s:
        dev = validate(s, st.query_params.get("tv"))
        site = dev.site_code if dev else None
    if site is None:
        record_failure(client)
        st.error("This TV code is invalid or has been revoked. Check the code or contact your Admin.")
        st.stop()

    @st.fragment(run_every="1m")
    def tv_screen():
        # token, screen and period are re-read on every refresh: revocation or changes apply within a minute.
        # The equipment screen is cached per published version, so refreshing it every minute costs nothing.
        with session_scope() as s:
            d = validate(s, st.query_params.get("tv"))
            period, screen = (d.period, d.screen) if d else (None, None)
            h_date, h_shift = (d.hourly_date, d.hourly_shift) if d else (None, None)
            review = (d.review_from, d.review_to) if d else None
        if period is None:
            st.error("This TV link has been revoked.")
            return
        if screen == "hourly":
            show_hourly(site, kiosk=True, date=h_date, shift=h_shift if h_date else None,
                        theme=st.query_params.get("theme", "dark"))     # &theme=light on the TV link
        else:
            show(site, kiosk=True, period=period, review=review)

    st.navigation([st.Page(tv_screen, title=f"TV {site}", url_path="tv")], position="hidden").run()
    st.stop()

user, auth = authenticate()
if user is None:
    st.session_state.pop("user", None)
    st.navigation([st.Page(lambda: None, title=f"Sign in · {brand.NAME}", url_path="login")], position="hidden").run()
    st.stop()
st.session_state["user"] = user


def P(path, title, icon):
    """Page spec (path, title, icon); the st.Page objects are made once the landing page and the waiting
    counts of this user are known."""
    return path, title, icon


DASH = {
    "overview": P("pages/dashboard/overview.py", "Overview", "dashboard"),
    "hourly": P("pages/dashboard/hourly.py", "Hourly production", "timer"),
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
    "upload": P("pages/data/upload.py", f"Upload {PRODUCTION_DATA}", "upload_file"),
    "approval": P("pages/data/approval.py", f"Approve {PRODUCTION_DATA}", "fact_check"),
    "shift_approval": P("pages/data/shift_approval.py", "Approve hourly shifts", "task_alt"),
    "upload_history": P("pages/data/upload_history.py", "Upload history", "history"),
    "data_explorer": P("pages/data/explorer.py", "Data explorer", "table_view"),
    "hourly_input": P("pages/data/hourly_input.py", "Input hourly production", "schedule_send"),
    "hourly_setup": P("pages/admin/hourly_setup.py", "Load factors", "scale"),
    "haul_routes": P("pages/admin/pit_disposal.py", "PIT & disposals", "alt_route"),
    "operators": P("pages/admin/operators.py", "Operators", "badge"),
    "unit_population": P("pages/admin/unit_population.py", f"Upload {UNIT_POPULATION}", "precision_manufacturing"),
    "delete_data": P("pages/admin/delete_data.py", "Delete data", "delete_forever"),
    "users_roles": P("pages/admin/users_roles.py", "Users & roles", "group"),
    "targets_plan": P("pages/admin/targets_plan.py", "Production targets", "flag"),
    "hourly_targets": P("pages/admin/hourly_targets.py", "Hourly targets", "avg_pace"),
    "pm_interval": P("pages/admin/pm_interval.py", "PM intervals & standby", "schedule"),
    "sites_mapping": P("pages/admin/sites_mapping.py", "Sites & mapping", "account_tree"),
    "display_devices": P("pages/admin/display_devices.py", "TV devices", "cast"),
    "audit_log": P("pages/admin/audit_log.py", "Audit log", "receipt_long"),
    "home": P("pages/home.py", "Data status", "info"),
    "account": P("pages/account.py", "Change password", "key"),
}


def allowed(key: str) -> bool:
    return user.role in PAGE_ROLES[key]


if st.session_state.pop("password_updated", False):
    st.toast("Password updated.")
if user.must_change_password:
    path, title, icon = OTHER["account"]
    nav = st.navigation([st.Page(path, title=title, icon=f":material/{icon}:")])
else:
    n = n_sh = 0
    if allowed("approval"):
        from core.ui import sites_for

        with session_scope() as s:
            n = repo.pending_count(s, sites_for(user))
            n_sh = repo.hourly_waiting_count(s, sites_for(user))
    # the page a user lands on: their daily task (data officer: hourly input; approver: what waits for them)
    if user.role == SITE_MANAGER:
        landing = "shift_approval" if n_sh else "approval" if n else "overview"
    else:
        landing = "hourly_input" if user.role == DATA_OFFICER else "overview"
    waiting = {"approval": n, "shift_approval": n_sh}

    def page(key: str, src: dict) -> st.Page:
        path, title, icon = src[key]
        title += f" ({waiting[key]} waiting)" if waiting.get(key) else ""
        return st.Page(path, title=title, icon=f":material/{icon}:", default=key == landing)

    pick = lambda keys, src=OTHER: [page(k, src) for k in keys if allowed(k)]  # noqa: E731
    # grouped by task: production results, equipment results, deeper analysis, bring data in, approve, run the
    # TVs, configure (the rarely used setup pages last)
    sections = {
        "Production": pick(["overview", "hourly", "production_ob", "coal_getting", "fuel"], DASH),
        "Equipment": pick(["pa_ua", "reliability", "time_distribution", "loader_fleet"], DASH),
        "Analysis": pick(["data_quality"], DASH) + pick(["data_explorer", "home"]),
        # the three datasets in the order they are needed: units first, then production, then hourly
        "Input & upload": pick(["unit_population", "upload", "hourly_input", "upload_history"]),
        "Approval": pick(["approval", "shift_approval"]),
        "TV": pick(["preview_tv", "display_devices"]),
        "Setup": pick(["targets_plan", "hourly_targets", "hourly_setup", "haul_routes", "operators", "sites_mapping",
                       "users_roles", "pm_interval", "audit_log", "delete_data"]),
        "Account": pick(["account"]),
    }
    if n or n_sh:  # something waits for this approver: put it first
        sections = {"Approval": sections.pop("Approval"), **sections}
    # expanded: every section stays visible (by default Streamlit folds all but ~10 links into "View N more",
    # which hid Input & upload, Approval and the setup pages)
    nav = st.navigation({k: v for k, v in sections.items() if v}, expanded=True)

brand.sidebar_logo()
st.html(T.css_vars())
# Streamlit's default ~6rem top padding leaves a large empty band above every page title
st.html("<style>[data-testid='stMainBlockContainer']{padding-top:1rem}"
        "[data-testid='stMainBlockContainer'] h1{padding-top:0}</style>")
with st.sidebar:
    st.markdown(f"**{user.name}**  \n{ROLE_LABEL[user.role]}")
    auth.logout("Sign out", location="sidebar", key="logout_btn",
                callback=lambda _info: st.session_state.pop("user", None))

nav.run()
