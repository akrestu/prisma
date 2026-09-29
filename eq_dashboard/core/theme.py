"""'Haul road' design tokens shared by the TV screen and the dashboard (Plotly template).

Asphalt and dust greys, chalk text, hi-vis yellow as the only accent. Orange means "bad": a missed target or Down time.
Ready/Down use blue/orange (safe for red-green colour blindness).
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


def miss_level(value, target, higher_better: bool = True):
    """None = no target · 0 = on target · 1 = small miss (≤10%) · 2 = real miss."""
    import pandas as pd
    if value is None or target is None or pd.isna(value) or target == 0:
        return None
    gap = (value - target) / abs(target) * (1 if higher_better else -1)
    return 0 if gap >= 0 else (1 if gap >= -MISS_THRESHOLD else 2)


def register_plotly() -> None:
    pio.templates["haulroad"] = go.layout.Template(layout=go.Layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=TEXT, size=13), title=dict(font=dict(size=15, color=TEXT), x=0, xanchor="left"),
        colorway=[ACCENT, READY, PA_COLOR, FUEL_COLOR, IDLE, STANDBY, "#A7D38B", MISS],
        xaxis=dict(gridcolor=LINE, linecolor=LINE, zeroline=False, tickcolor=LINE, tickfont=dict(color=MUTED)),
        yaxis=dict(gridcolor=LINE, linecolor="rgba(0,0,0,0)", zeroline=False, tickfont=dict(color=MUTED)),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=MUTED), orientation="h", y=1.08, x=0),
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=LINE, font=dict(family=FONT, color=TEXT)),
        separators=".,",
    ))
    pio.templates.default = "haulroad"
