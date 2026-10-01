"""PRISMA branding: name, logo assets and the sign-in screen layout."""
from __future__ import annotations

import base64
import html
from functools import lru_cache
from pathlib import Path

import streamlit as st

from core import theme as T

NAME = "PRISMA"
FULL_NAME = "Production & Reliability Information System for Mining Analytics"
COMPANY = "PT WBK"
BRAND_DIR = Path(__file__).resolve().parent.parent / "static" / "brand"
ICON = str(BRAND_DIR / "logo-128.png")
FAVICON = str(BRAND_DIR / "logo-64.png")
WORDMARK = str(BRAND_DIR / "wordmark.png")              # chalk text, for dark backgrounds
WORDMARK_LIGHT = str(BRAND_DIR / "wordmark-light.png")  # dark text, for the light theme


@lru_cache
def data_uri(name: str) -> str:
    return "data:image/png;base64," + base64.b64encode((BRAND_DIR / name).read_bytes()).decode()


def sidebar_logo() -> None:
    st.logo(WORDMARK_LIGHT if T.is_light() else WORDMARK, size="large", icon_image=ICON)


# Road-cut stripes echoing the logo's curves: a quiet texture behind the brand panel, not decoration for its own sake.
_STRIPES = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 700" preserveAspectRatio="xMidYMid slice">
<g fill="none" stroke="{T.ACCENT}" stroke-linecap="round" opacity=".13">
<path d="M-40 520 C 160 600, 380 560, 640 250" stroke-width="46"/>
<path d="M-40 640 C 200 720, 460 640, 660 380" stroke-width="30"/>
<path d="M-40 400 C 140 460, 330 430, 620 120" stroke-width="18"/>
</g></svg>"""

def login_css() -> str:
    """Sign-in layout, centred in the viewport. Both panels follow light/dark through the --pr-* CSS variables,
    so a theme switch restyles it instantly."""
    stripes = base64.b64encode(_STRIPES.encode()).decode()
    k = ".st-key-login_shell"
    return T.css_vars() + f"""<style>
[data-testid="stMainBlockContainer"]{{max-width:1040px;padding-top:0;padding-bottom:0}}
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"]{{gap:0}}
.st-key-init{{position:absolute;height:0;overflow:hidden}}  /* cookie-manager iframe: mounted, but takes no room */
header[data-testid="stHeader"]{{background:transparent}}
{k}{{min-height:100dvh;box-sizing:border-box;padding:56px 0 24px;display:flex;flex-direction:column;justify-content:center}}
{k} [data-testid="stHorizontalBlock"]{{gap:0;border:1px solid var(--pr-line);border-radius:10px;overflow:hidden;
  background:var(--pr-surface);align-items:stretch;box-shadow:0 12px 40px light-dark(rgba(0,0,0,.08),rgba(0,0,0,.35))}}
{k} [data-testid="stColumn"]:first-child{{background:var(--pr-bg) url("data:image/svg+xml;base64,{stripes}")
  center/cover no-repeat;border-right:1px solid var(--pr-line)}}
{k} [data-testid="stColumn"]:last-child{{padding:48px 48px 40px;display:flex;flex-direction:column;justify-content:center}}
{k} [data-testid="stForm"]{{border:0;padding:0}}
{k} [data-testid="stForm"] h3{{font-size:1.6rem;font-weight:600;letter-spacing:-.01em;padding:0 0 1.1rem;color:var(--pr-text)}}
{k} [data-testid="stHeaderActionElements"]{{display:none}}
{k} [data-testid="stWidgetLabel"] p{{font-size:.9rem;font-weight:500;color:var(--pr-text)}}
{k} [data-testid="stTextInputRootElement"]{{background:var(--pr-bg);border:1px solid var(--pr-field);border-radius:6px;
  height:2.75rem;transition:border-color .15s,box-shadow .15s}}
{k} [data-testid="stTextInputRootElement"]:hover{{border-color:var(--pr-muted)}}
{k} [data-testid="stTextInputRootElement"]:focus-within{{border-color:{T.ACCENT};box-shadow:0 0 0 3px {T.ACCENT}40}}
{k} [data-testid="stTextInputField"]{{color:var(--pr-text);background:transparent;font-size:1rem}}
{k} [data-testid="stElementContainer"]:has([data-testid="stFormSubmitButton"]),
{k} [data-testid="stElementContainer"]:has([data-testid="stFormSubmitButton"]) > div{{width:100%;margin-top:.5rem}}
{k} [data-testid="stFormSubmitButton"] button{{width:100%;background:{T.ACCENT};color:#141517;border:0;border-radius:6px;
  font-weight:600;font-size:1rem;height:2.9rem;transition:background .15s}}
{k} [data-testid="stFormSubmitButton"] button p{{font-size:1rem;font-weight:600}}
{k} [data-testid="stFormSubmitButton"] button:hover{{background:#FFD447;color:#141517}}
{k} [data-testid="stFormSubmitButton"] button:focus-visible{{outline:2px solid var(--pr-text);outline-offset:2px}}
.wp-brand{{padding:48px 44px;min-height:480px;height:100%;box-sizing:border-box;display:flex;flex-direction:column;
  justify-content:space-between}}
.wp-brand img{{width:72px;height:72px}}
.wp-name{{font-size:3.4rem;font-weight:700;letter-spacing:.02em;line-height:1;margin:24px 0 12px;color:var(--pr-text)}}
.wp-full{{font-size:1.05rem;line-height:1.4;color:var(--pr-text);max-width:22ch;text-wrap:balance}}
.wp-what{{font-size:.92rem;line-height:1.6;color:var(--pr-muted);max-width:36ch;margin-top:20px}}
.wp-co{{font-size:.8rem;color:var(--pr-dim);letter-spacing:.06em}}
.wp-help{{font-size:.85rem;color:var(--pr-muted);margin-top:20px;padding-top:16px;border-top:1px solid var(--pr-line)}}
@media (max-width:640px){{
  .wp-brand{{min-height:0;padding:28px 24px}}.wp-name{{font-size:2.4rem;margin:16px 0 8px}}.wp-what{{display:none}}
  .wp-brand img{{width:52px;height:52px}}.wp-co{{margin-top:16px}}
  {k} [data-testid="stColumn"]:first-child{{border-right:0;border-bottom:1px solid var(--pr-line)}}
  {k} [data-testid="stColumn"]:last-child{{padding:28px 24px}}}}
</style>"""


def brand_panel() -> None:
    st.html(f"""<div class="wp-brand"><div>
<img src="{data_uri('logo-128.png')}" alt="WBK logo">
<div class="wp-name">{NAME}</div>
<div class="wp-full">{html.escape(FULL_NAME)}</div>
<div class="wp-what">Equipment availability, reliability, production and fuel for every site,
from the Production Data workbook to the control-room TV.</div>
</div><div class="wp-co">{COMPANY}</div></div>""")


def login_help() -> None:
    st.html('<div class="wp-help">No account yet, or locked out? Ask your site Admin.</div>')
