"""WANPIS branding: name, logo assets and the sign-in screen layout."""
from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st

from core import theme as T

NAME = "WANPIS"
FULL_NAME = "Wahana Production Analysis Information System"
COMPANY = "PT WBK"
BRAND_DIR = Path(__file__).resolve().parent.parent / "static" / "brand"
ICON = str(BRAND_DIR / "logo-128.png")
FAVICON = str(BRAND_DIR / "logo-64.png")
WORDMARK = str(BRAND_DIR / "wordmark.png")


@lru_cache
def data_uri(name: str) -> str:
    return "data:image/png;base64," + base64.b64encode((BRAND_DIR / name).read_bytes()).decode()


def sidebar_logo() -> None:
    st.logo(WORDMARK, size="large", icon_image=ICON)


# Road-cut stripes echoing the logo's curves: a quiet texture behind the brand panel, not decoration for its own sake.
_STRIPES = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 700" preserveAspectRatio="xMidYMid slice">
<g fill="none" stroke="{T.ACCENT}" stroke-linecap="round" opacity=".13">
<path d="M-40 520 C 160 600, 380 560, 640 250" stroke-width="46"/>
<path d="M-40 640 C 200 720, 460 640, 660 380" stroke-width="30"/>
<path d="M-40 400 C 140 460, 330 430, 620 120" stroke-width="18"/>
</g></svg>"""

LOGIN_CSS = f"""<style>
[data-testid="stMainBlockContainer"]{{max-width:1080px;padding-top:9vh}}
header[data-testid="stHeader"]{{background:transparent}}
.st-key-login_shell [data-testid="stHorizontalBlock"]{{gap:0;border:1px solid {T.LINE};border-radius:6px;overflow:hidden;
  background:{T.SURFACE};align-items:stretch}}
.st-key-login_shell [data-testid="stColumn"]:first-child{{background:{T.BG}
  url("data:image/svg+xml;base64,{base64.b64encode(_STRIPES.encode()).decode()}") center/cover no-repeat;
  border-right:1px solid {T.LINE}}}
.st-key-login_shell [data-testid="stColumn"]:last-child{{padding:44px 44px 36px}}
.st-key-login_shell [data-testid="stForm"]{{border:0;padding:0}}
.st-key-login_shell [data-testid="stForm"] h1,.st-key-login_shell [data-testid="stForm"] h2,
.st-key-login_shell [data-testid="stForm"] h3{{font-size:1.45rem;font-weight:600;padding:0 0 .2rem}}
.st-key-login_shell [data-testid="stFormSubmitButton"] button{{width:100%;background:{T.ACCENT};color:#141517;
  border:0;font-weight:600;height:2.75rem}}
.st-key-login_shell [data-testid="stFormSubmitButton"] button:hover{{background:#FFD447;color:#141517}}
.wp-brand{{padding:44px 40px;min-height:470px;display:flex;flex-direction:column;justify-content:space-between}}
.wp-brand img{{width:76px;height:76px}}
.wp-name{{font-size:3.4rem;font-weight:700;letter-spacing:.02em;line-height:1;margin:22px 0 10px;color:{T.TEXT}}}
.wp-full{{font-size:1.05rem;line-height:1.4;color:{T.TEXT};max-width:22ch}}
.wp-what{{font-size:.92rem;line-height:1.55;color:{T.MUTED};max-width:34ch;margin-top:18px}}
.wp-co{{font-size:.8rem;color:{T.DIM};letter-spacing:.04em}}
.wp-help{{font-size:.82rem;color:{T.DIM};margin-top:18px}}
@media (max-width:640px){{.wp-brand{{min-height:0;padding:28px 24px}}.wp-name{{font-size:2.6rem}}
  .st-key-login_shell [data-testid="stColumn"]:last-child{{padding:28px 24px}}}}
</style>"""


def brand_panel() -> None:
    st.html(f"""<div class="wp-brand"><div>
<img src="{data_uri('logo-128.png')}" alt="WBK logo">
<div class="wp-name">{NAME}</div>
<div class="wp-full">{FULL_NAME}</div>
<div class="wp-what">Equipment availability, reliability, production and fuel for every site,
from the monthly Data_Prod workbook to the control-room TV.</div>
</div><div class="wp-co">{COMPANY}</div></div>""")


def login_help() -> None:
    st.html('<div class="wp-help">No account yet, or locked out? Ask your site Admin.</div>')
