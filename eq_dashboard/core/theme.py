"""'Haul road' design tokens shared by the TV screen and the dashboard (Plotly template).

Asphalt and dust greys, chalk text, hi-vis yellow as the only accent. Orange means "bad": a missed target or Down time.
Ready/Down use blue/orange (safe for red-green colour blindness).
The module constants are the dark tokens (TV screens are always dark). The dashboard follows the viewer's
light/dark choice through `tokens()`; data colours are shared by both modes.
"""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

BG = "#141517"        # asphalt
SURFACE = "#1C1E21"   # road base
LINE = "#2C2F33"
TEXT = "#EDEAE3"      # chalk
MUTED = "#9C9A93"
DIM = "#8A8880"       # ≥4.5:1 on BG (WCAG AA for small text)
ACCENT = "#F2C230"    # hi-vis
MISS = "#F08A3C"      # off target
READY, IDLE, STANDBY, DOWN = "#4E9BD8", "#9CC7EA", "#C98DA8", "#F08A3C"  # standby = dusty rose
CAT = {"R": READY, "I": IDLE, "S": STANDBY, "D": DOWN}
NEUTRAL_BAR = "#7CCFB9"  # default category bars: soft teal, never grey/white
FUEL_COLOR = "#C08BE0"   # violet: fuel litres (never status colours)
PA_COLOR = "#4FC1A6"     # teal: PA series (distinct from chalk text, blue UoA, orange miss)
METRIC_COLOR = {"PA": PA_COLOR, "UoA": READY, "MA": IDLE, "EU": "#A7D38B"}  # same as trend lines and the TV
FONT = "IBM Plex Sans, Segoe UI, Arial, sans-serif"
MISS_THRESHOLD = 0.10    # more than 10% worse than target = real miss (orange)

DARK = {"BG": BG, "SURFACE": SURFACE, "LINE": LINE, "TEXT": TEXT, "MUTED": MUTED, "DIM": DIM,
        "FIELD": "#6A6E75"}   # FIELD: input borders, ≥3:1 against the surface (WCAG non-text contrast)
# light: paper and concrete greys; MUTED and DIM keep ≥4.5:1 on BG
LIGHT = {"BG": "#F7F6F2", "SURFACE": "#ECEAE4", "LINE": "#D8D5CD", "TEXT": "#1E1F21", "MUTED": "#55534E",
         "DIM": "#686660", "FIELD": "#85817A"}

# Plotly colours that follow the viewer's theme: Streamlit's frontend swaps these placeholders for the active
# theme's colours on every render and theme switch (streamlit/elements/lib/streamlit_plotly_theme.py).
INK = "#000037"        # body text: #fafafa on dark, #262730 on light


def css_vars() -> str:
    """Theme tokens as CSS custom properties. `light-dark()` follows the color-scheme Streamlit sets on .stApp,
    so custom HTML switches with the theme instantly, with no rerun (st.context.theme lags a theme change)."""
    names = ("BG", "SURFACE", "LINE", "TEXT", "MUTED", "DIM", "FIELD")
    body = ";".join(f"--pr-{n.lower()}:light-dark({LIGHT[n]},{DARK[n]})" for n in names)
    return f"<style>.stApp{{{body};--pr-accent:{ACCENT}}}</style>"


def is_light() -> bool:
    """Best guess of the viewer's theme, for the few things CSS cannot switch (the sidebar logo image).
    It may lag one rerun behind a theme change; prefer css_vars() / INK for colours."""
    import streamlit as st
    try:
        return st.context.theme.type == "light"
    except Exception:   # outside a script run (tests, CLI)
        return False


def miss_level(value, target, higher_better: bool = True):
    """None = no target · 0 = on target · 1 = small miss (≤10%) · 2 = real miss."""
    import pandas as pd
    if value is None or target is None or pd.isna(value) or target == 0:
        return None
    gap = (value - target) / abs(target) * (1 if higher_better else -1)
    return 0 if gap >= 0 else (1 if gap >= -MISS_THRESHOLD else 2)


def register_plotly() -> None:
    """'haulroad' adds our data palette, font and legend placement on top of Streamlit's own Plotly theme, which
    keeps text, grid and hover colours in step with light/dark. Use it as template "streamlit+haulroad"."""
    pio.templates["haulroad"] = go.layout.Template(layout=go.Layout(
        font=dict(family=FONT, size=13), title=dict(font=dict(size=15), x=0, xanchor="left"),
        colorway=[ACCENT, READY, PA_COLOR, FUEL_COLOR, IDLE, STANDBY, "#A7D38B", MISS],
        xaxis=dict(zeroline=False), yaxis=dict(zeroline=False),
        legend=dict(orientation="h", y=1.08, x=0),
        hoverlabel=dict(font=dict(family=FONT)),
        separators=".,",
    ))
    pio.templates.default = "streamlit+haulroad"
