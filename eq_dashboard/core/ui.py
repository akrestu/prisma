"""Shared UI helpers for Streamlit pages (English text, English number format 1,234.5)."""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from auth.access import CurrentUser, allowed_sites, can_open
from db.engine import session_scope

STATUS_BADGE = {"PENDING": ":orange-badge[PENDING]", "PUBLISHED": ":green-badge[PUBLISHED]",
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


def excel_download(df: pd.DataFrame, filename: str, label: str = "Download Excel", key: str | None = None) -> None:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False)
    st.download_button(label, buf.getvalue(), file_name=filename, key=key,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
