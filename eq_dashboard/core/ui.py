"""Shared UI helpers for Streamlit pages (English text, English number format 1,234.5)."""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from auth.access import CurrentUser, allowed_sites, can_open
from db.engine import session_scope

# design system: hi-vis yellow = live/published, orange = needs action, red = rejected, gray = inactive/history
STATUS_BADGE = {"PENDING": ":orange-badge[PENDING]", "PUBLISHED": ":yellow-badge[PUBLISHED]",
                "REJECTED": ":red-badge[REJECTED]", "SUPERSEDED": ":gray-badge[SUPERSEDED]"}


def current_user() -> CurrentUser | None:
    return st.session_state.get("user")


def require(page: str) -> CurrentUser:
    """Guard at the top of every page (second layer after st.navigation)."""
    user = current_user()
    if not can_open(user, page):
        st.error("You do not have access to this page.")
        st.stop()
    return user


def sites_for(user: CurrentUser) -> list[str]:
    with session_scope() as s:
        return allowed_sites(s, user)


def fmt_num(v, d: int = 0) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:,.{d}f}"


def fmt_pct(v, d: int = 1) -> str:
    return "—" if v is None or pd.isna(v) else f"{v * 100:.{d}f}%"


def excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False)
    return buf.getvalue()


def excel_download(df: pd.DataFrame, filename: str, label: str = "Download Excel", key: str | None = None) -> None:
    """The workbook is built only when the button is clicked (deferred download), not on every rerun:
    writing Excel is the slowest step on most pages (≈10 s for 60,000 rows)."""
    st.download_button(label, lambda: excel_bytes(df), file_name=filename, key=key, on_click="ignore",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def refresh(*what: str) -> None:
    """Clear only the caches whose inputs just changed, instead of every cache of every user (st.cache_data.clear()
    made each save slow down all dashboards and TVs). Data tables are cached per upload and an upload never changes
    after import, and the equipment TV is keyed by the published versions and target values, so imports, approvals
    and target edits need nothing here.
      "plan"   daily production plan       "pm"  PM intervals and standby groups
      "hourly" hourly TV payload           "all" everything (after deleting data)"""
    if "all" in what:
        st.cache_data.clear()
        return
    from core import dash
    if "plan" in what:
        dash.plan_daily.clear()
    if "pm" in what:
        dash.pm_intervals.clear()
        dash.client_standby_codes.clear()
    if "hourly" in what:
        from pages.tv.screen import _hourly_payload
        _hourly_payload.clear()


def copy_button(text: str, label: str = "Copy link") -> None:
    """One-click copy to the clipboard, with feedback. st.html strips inline handlers (onclick), so a small script
    right after the button binds it; there is a fallback for browsers without the Clipboard API (plain http)."""
    import html
    import json
    st.html(
        f"<button class='cpy' type='button' data-v=\"{html.escape(json.dumps(text), quote=True)}\">"
        f"{html.escape(label)}</button>"
        "<script>(function(){const b=document.currentScript.previousElementSibling;if(!b)return;"
        "b.addEventListener('click',function(){const t=JSON.parse(b.dataset.v),l=b.textContent;"
        "const ok=()=>{b.textContent='Copied ✓';setTimeout(()=>{b.textContent=l},1600)};"
        "const old=()=>{const a=document.createElement('textarea');a.value=t;a.style.position='fixed';"
        "a.style.opacity='0';document.body.appendChild(a);a.select();"
        "const done=document.execCommand('copy');a.remove();"
        "if(done){ok()}else{window.prompt('Copy this link (Ctrl+C):',t)}};"
        "if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(ok,old)}else{old()}"
        "})})()</script>"
        "<style>.cpy{font:inherit;font-size:.85rem;padding:.25rem .7rem;border-radius:.4rem;cursor:pointer;"
        "border:1px solid rgba(128,128,128,.45);background:transparent;color:inherit}"
        ".cpy:hover{border-color:currentColor}</style>",
        unsafe_allow_javascript=True, width="content")
