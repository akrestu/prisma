"""Render the TV screen as HTML + SVG (no JavaScript) for st.html — 'haul road' design.

Layout (1920×1080, one screen): the latest slice of the period leads on the left (UoA & PA vs target, time split,
one summary sentence); the right side carries secondary KPIs, trend, production, PA & hours by type,
productivity & haul distance, down components and longest-down units; the footer keeps fleet facts.
Charts are SVG images (<img src="data:image/svg+xml;base64,...">) because st.html strips inline <svg>.
One font everywhere: IBM Plex Sans, self-hosted (/app/static/fonts) and embedded in the chart SVGs.
"""
from __future__ import annotations

import base64
import datetime as dt
import re
from functools import lru_cache
from html import escape
from pathlib import Path

import pandas as pd

from core import theme as T
from core.periods import PERIOD_LABEL
from core.tv import Kpi, TvData

WIB = dt.timezone(dt.timedelta(hours=7))
FONT = "'IBM Plex Sans', 'Segoe UI', Roboto, Arial, sans-serif"
FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
SHORT_TYPE = {"Supporting Equipment": "Support equip."}
ACRONYMS = {"Pm": "PM", "Get": "GET", "Usm": "USM", "Sm": "SM", "Ac": "AC", "Ob": "OB", "Cg": "CG"}


@lru_cache(maxsize=1)
def _font_face() -> str:
    """@font-face with the font embedded, for SVG images (they cannot load page fonts)."""
    f = FONT_DIR / "ibm-plex-sans-500.woff2"
    if not f.exists():
        return ""
    b64 = base64.b64encode(f.read_bytes()).decode()
    return (f"<style>@font-face{{font-family:'IBM Plex Sans';font-weight:100 900;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}</style>")


def n(v, d=0) -> str:
    """English number format: 1,234.5"""
    return "—" if v is None or pd.isna(v) else f"{v:,.{d}f}"


def pct(v, d=1) -> str:
    return "—" if v is None or pd.isna(v) else f"{v * 100:.{d}f}%"


def nice(text) -> str:
    """'PERIODIC SERVICE - PM' → 'Periodic service - PM'."""
    words = str(text or "").lower().capitalize().split(" ")
    return " ".join(ACRONYMS.get(w.capitalize(), w) for w in words)


def _svg(w: int, h: int, body: str) -> str:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet" '
           f'font-family="{FONT}">{_font_face()}{body}</svg>')
    return f'<img class="chart" alt="" src="data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}">'


def _t(x, y, s, size=16, anchor="start", fill=None, weight=None) -> str:
    w = f' font-weight="{weight}"' if weight else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" '
            f'fill="{fill or T.MUTED}"{w}>{escape(str(s))}</text>')


def _delta(value, target, unit, higher_better=True) -> str:
    """'▼ 31.9 pt vs 60%' — orange only for a real miss (> 10% of target)."""
    if value is None or pd.isna(value):
        return ""
    if target is None:
        return f'<span class="dim">no target</span>'
    diff = value - target
    arrow = "▲" if diff >= 0 else "▼"
    if unit == "%":
        body = f"{arrow} {abs(diff) * 100:.1f} pt vs {n(target * 100, 0 if round(target * 100, 1) % 1 == 0 else 1)}%"
    elif unit in ("BCM", "t"):
        body = f"{arrow} {n(abs(diff))} vs plan ({n(value / target * 100, 0)}%)" if target else ""
    else:
        body = f"{arrow} {n(abs(diff), 1)} {unit} vs {n(target, 0)}"
    cls = "miss" if T.miss_level(value, target, higher_better) == 2 else "ok"
    return f'<span class="{cls}">{body}</span>'


# ------------------------------------------------------------------ hero (left column)
def _hero_metric(label: str, value, target, range_name: str, range_value) -> str:
    cls = "miss" if T.miss_level(value, target) == 2 else ""
    return (f'<div class="hm"><div class="hl">{label}</div><div class="big {cls}">{pct(value)}</div>'
            f'<div class="hd">{_delta(value, target, "%")}</div>'
            f'<div class="hr">{escape(range_name)} {pct(range_value)}</div></div>')


def _split_bar(h: dict) -> str:
    parts = [("Ready", h.get("ready"), T.READY), ("Idle", h.get("idle"), T.IDLE),
             ("Standby", h.get("standby"), T.STANDBY), ("Down", h.get("down"), T.DOWN)]
    bar = "".join(f'<i style="width:{(v or 0) * 100:.2f}%;background:{c}"></i>' for _, v, c in parts)
    legend = "".join(f'<span><i style="background:{c}"></i>{lab} {pct(v, 0)}</span>' for lab, v, c in parts)
    return f'<div class="split"><div class="hl">Time split</div><div class="sb">{bar}</div><div class="lg">{legend}</div></div>'


def _headline(d: TvData, uoa_target) -> str:
    """One sentence that says what matters most, using the hero numbers."""
    h = d.hero
    parts = []
    lvl = T.miss_level(h.get("uoa"), uoa_target)
    if lvl is not None and lvl > 0:
        parts.append(f"UoA {abs(h['uoa'] - uoa_target) * 100:.0f} pt below target ({h['label'].split('·')[-1].strip()})")
    elif lvl == 0:
        parts.append("UoA on target")
    if len(d.components):
        share = d.components.iloc[0]["hours"] / d.components["hours"].sum()
        parts.append(f"{nice(d.components.iloc[0]['reason'])} is {share:.0%} of the top down hours")
    if d.footer.get("down_now"):
        parts.append(f"{d.footer['down_now']} units down at the latest record")
    return ". ".join(parts) + "." if parts else "All tracked KPIs are on target."


# ------------------------------------------------------------------ secondary KPIs
def _kpi_html(k: Kpi) -> str:
    if k.value is None or pd.isna(k.value):
        val, dl = "—", f'<span class="dim">{escape(k.note or "no data")}</span>'
    elif k.unit == "%":
        val, dl = f"{k.value * 100:.1f}<small>%</small>", _delta(k.value, k.target, "%", k.higher_better)
    elif k.unit == "h":
        val, dl = f"{k.value:,.1f}<small>h</small>", _delta(k.value, k.target, "h", k.higher_better)
    else:
        val = f"{k.value:,.0f}<small>{k.unit}</small>"
        dl = _delta(k.value, k.target, k.unit) if k.target is not None else '<span class="dim">no plan</span>'
    return (f'<div class="kp"><div class="kl">{escape(k.label)}</div><div class="kv">{val}</div>'
            f'<div class="kd">{dl}</div><div class="ks">{escape(k.sub)}</div></div>')


# ------------------------------------------------------------------ charts
def _xlabels(labels, x_of, y, max_labels=8, size=16):
    step = max(1, -(-len(labels) // max_labels))
    last = len(labels) - 1
    keep = [i for i in range(len(labels)) if i % step == 0]
    if keep and last - keep[-1] >= step:
        keep.append(last)
    return [_t(x_of(i), y, labels[i], size, "middle", T.DIM) for i in keep]


def _trend_svg(d: TvData) -> str:
    df = d.trend
    W, H, x0, x1, y0, y1 = 800, 300, 56, 700, 18, 256
    if df.empty:
        return _svg(W, H, "")
    k = len(df)
    X = (lambda i: (x0 + x1) / 2) if k == 1 else (lambda i: x0 + i * (x1 - x0) / (k - 1))
    Y = lambda v: y1 - v * (y1 - y0)  # noqa: E731
    out = []
    for g in (0, .5, 1):
        out.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(g):.1f}" y2="{Y(g):.1f}" stroke="{T.LINE}"/>')
        out.append(_t(x0 - 10, Y(g) + 6, f"{int(g * 100)}%", 16, "end", T.DIM))
    if d.uoa_target is not None:
        yt = Y(d.uoa_target)
        out.append(f'<line x1="{x0}" x2="{x1}" y1="{yt:.1f}" y2="{yt:.1f}" stroke="{T.ACCENT}" stroke-width="2" stroke-dasharray="2 7"/>')
        out.append(_t(x0 + 6, yt - 9, f"UoA target {d.uoa_target * 100:.0f}%", 16, "start", T.ACCENT))
    for col, color in (("PA", T.TEXT), ("UoA", T.READY)):
        pts = [(X(i), Y(v)) for i, (v, ok) in enumerate(zip(df[col], df["complete"])) if ok and pd.notna(v)]
        if len(pts) > 1:
            out.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" fill="none" '
                       f'stroke="{color}" stroke-width="3.5" stroke-linejoin="round"/>')
        for i, (v, ok) in enumerate(zip(df[col], df["complete"])):
            if pd.notna(v) and (not ok or k <= 12):
                fill = color if ok else T.BG
                out.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="5" fill="{fill}" stroke="{color}" stroke-width="2.5"/>')
        if pts:
            v = [v for v, ok in zip(df[col], df["complete"]) if ok and pd.notna(v)][-1]
            a, b = pts[-1]
            out.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="6" fill="{color}"/>')
            out.append(_t(x1 + 14, b + 6, f"{col} {v * 100:.0f}%", 18, "start", color, 600))
    out += _xlabels(list(df["label"]), X, y1 + 30)
    return _svg(W, H, "".join(out))


def _short(v: float) -> str:
    if not v:
        return "0"
    return f"{v / 1000:,.0f}k" if v >= 10000 else (f"{v / 1000:,.1f}k" if v >= 1000 else f"{v:,.0f}")


def _bars(out, vals, plans, x0, x1, ya, yb, color, label):
    k = max(len(vals), 1)
    top = max([*vals, *[p for p in plans if pd.notna(p)], 1]) * 1.12
    bw = (x1 - x0) / k
    Y = lambda v: yb - v / top * (yb - ya)  # noqa: E731
    out.append(f'<line x1="{x0}" x2="{x1}" y1="{yb:.1f}" y2="{yb:.1f}" stroke="{T.LINE}"/>')
    out.append(_t(x1, ya - 4, f"max {_short(max(vals) if vals else 0)}", 15, "end", T.DIM))
    for i, v in enumerate(vals):
        out.append(f'<rect x="{x0 + i * bw + 1.5:.1f}" y="{Y(v):.1f}" width="{max(bw - 3, 1):.1f}" '
                   f'height="{yb - Y(v):.1f}" fill="{color}"/>')
    if any(pd.notna(p) for p in plans):
        pts = " ".join(f"{x0 + (i + .5) * bw:.1f},{Y(p):.1f}" for i, p in enumerate(plans) if pd.notna(p))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{T.TEXT}" stroke-width="2" stroke-dasharray="5 5"/>')
    out.append(_t(x0, ya - 4, label, 16, fill=T.TEXT, weight=600))
    return bw


def _prod_svg(d: TvData) -> str:
    p = d.prod
    W, H = 600, 300
    if p.empty:
        return _svg(W, H, _t(300, 150, "No production data", 18, "middle"))
    out = []
    bw = _bars(out, p["ob"].tolist(), p["ob_plan"].tolist(), 34, 590, 26, 128, T.ACCENT, "OB · BCM")
    _bars(out, p["coal"].tolist(), p["coal_plan"].tolist(), 34, 590, 168, 262, T.READY, "Coal · t")
    out += _xlabels(list(p["label"]), lambda i: 34 + (i + .5) * bw, 290, 6)
    return _svg(W, H, "".join(out))


def _type_svg(d: TvData, pa_target) -> str:
    """PA and hour split (Ready/Idle/Standby/Down) per equipment type, one row each."""
    bt = d.by_type.head(7)
    W, rh = 480, 34
    H = max(len(bt), 1) * rh + 6
    lx, x1 = 170, 408
    out = []
    for i, r in enumerate(bt.itertuples()):
        y, x = 4 + i * rh, lx
        label = SHORT_TYPE.get(str(r.type), str(r.type))
        out.append(_t(lx - 10, y + 23, label[:17], 19, "end", T.TEXT))
        for v, c in ((r.Rp, T.READY), (r.Ip, T.IDLE), (r.Sp, T.STANDBY), (r.Dp, T.DOWN)):
            w = (x1 - lx) * (v if pd.notna(v) else 0)
            out.append(f'<rect x="{x:.1f}" y="{y + 8}" width="{max(w - 1, 0):.1f}" height="20" fill="{c}"/>')
            x += w
        miss = T.miss_level(r.PA, pa_target) == 2
        out.append(_t(x1 + 12, y + 24, f"{r.PA * 100:.0f}%", 20, "start", T.MISS if miss else T.TEXT, 600))
    return _svg(W, H, "".join(out))


# ------------------------------------------------------------------ HTML panels
def _productivity_html(d: TvData) -> str:
    head = '<tr><th></th><th>per loader</th><th>per hauler</th><th>haul distance</th></tr>'
    rows = []
    for grp, unit, label in (("OB", "BCM/h", "OB"), ("CG", "t/h", "Coal")):
        p = d.productivity.get(grp) or {}
        if not p or not p.get("volume"):
            rows.append(f'<tr><td class="g">{label}</td><td colspan="3" class="dim">no trips</td></tr>')
            continue
        rows.append(
            f'<tr><td class="g">{label}<small>{p["loaders"]} loaders · {p["haulers"]} haulers</small></td>'
            f'<td><b>{n(p["loader_per_hour"])}</b><small>{unit}</small></td>'
            f'<td><b>{n(p["hauler_per_hour"], 1)}</b><small>{unit} · {n(p["rit_per_hour"], 2)} trips/h</small></td>'
            f'<td><b>{n((p["dist_h"] or 0) / 1000, 2)} km</b><small>horizontal · {n(p["dist_v"])} m vertical</small></td></tr>')
    return f'<table class="tprod">{head}{"".join(rows)}</table>'


def _components_html(d: TvData) -> str:
    c = d.components.head(4)
    if c.empty:
        return '<div class="dim">No down hours.</div>'
    top, tot = c["hours"].max(), d.components["hours"].sum()
    return "".join(f'<div class="row"><span>{escape(nice(r.reason))}</span><span class="rn">{n(r.hours)} h · '
                   f'{r.hours / tot:.0%}</span><div class="rb"><i style="width:{r.hours / top * 100:.1f}%"></i></div></div>'
                   for r in c.itertuples())


def _units_html(d: TvData) -> str:
    bu = d.bad_units
    if bu.empty:
        return '<div class="dim">No units down.</div>'
    rows = []
    for r in bu.head(3).itertuples():
        tag = " · all period" if r.full_period else (" · down now" if r.down_now else "")
        rows.append(f'<div class="row"><span><b>{escape(r.unit)}</b> <span class="dim">{escape(str(r.model or ""))}</span>'
                    f'<br><span class="dim">{escape(nice(r.reason))}</span></span>'
                    f'<span class="rn">{n(r.hours)} h<span class="miss">{tag}</span></span></div>')
    if len(bu) > 3:
        rows.append(f'<div class="more dim">+ {len(bu) - 3} more: {", ".join(escape(u) for u in bu["unit"].iloc[3:])}</div>')
    return "".join(rows)


def _title(d: TvData) -> str:
    return {"hourly": "by hour", "daily": "day by day", "weekly": "by week", "monthly": "by month",
            "yearly": "by year"}[d.period]


CSS = """
@font-face{font-family:'IBM Plex Sans';font-weight:400;src:url(/app/static/fonts/ibm-plex-sans-400.woff2) format('woff2')}
@font-face{font-family:'IBM Plex Sans';font-weight:500;src:url(/app/static/fonts/ibm-plex-sans-500.woff2) format('woff2')}
@font-face{font-family:'IBM Plex Sans';font-weight:600;src:url(/app/static/fonts/ibm-plex-sans-600.woff2) format('woff2')}
@font-face{font-family:'IBM Plex Sans';font-weight:700;src:url(/app/static/fonts/ibm-plex-sans-700.woff2) format('woff2')}
.tv{container-type:inline-size;background:%(BG)s;color:%(TEXT)s;font-family:%(F)s;font-variant-numeric:tabular-nums;
 box-sizing:border-box;padding:1.1cqw 1.4cqw;display:grid;grid-template-columns:26%% 1fr;
 grid-template-rows:auto minmax(0,1fr) auto;gap:.9cqw 1.4cqw;overflow:hidden}
.tv.preview{aspect-ratio:16/9;width:100%%;border-radius:4px}
.tv.kiosk{width:min(100vw,177.78vh);height:min(100vh,56.25vw);margin:0 auto}
.tv *{box-sizing:border-box;font-family:%(F)s;min-width:0}
.tv .dim{color:%(DIM)s}.tv .miss{color:%(MISS)s}.tv .ok{color:%(MUTED)s}
.th{grid-column:1/3;display:flex;justify-content:space-between;align-items:baseline;gap:1cqw;border-bottom:.1cqw solid %(LINE)s;padding-bottom:.55cqw}
.th .site{font-size:2.2cqw;font-weight:700;letter-spacing:-.02em}
.th .per{font-size:1.15cqw;font-weight:600;color:%(ACCENT)s;margin-left:1cqw}
.th .rng{font-size:1.05cqw;color:%(MUTED)s;margin-left:1cqw}
.th .clk{font-size:2cqw;font-weight:600}
.hero{display:flex;flex-direction:column;gap:.8cqw;border-right:.1cqw solid %(LINE)s;padding-right:1.4cqw;min-height:0}
.hero .when{font-size:1.1cqw;color:%(MUTED)s}
.hm{display:grid;gap:.05cqw}
.hl{font-size:1.1cqw;color:%(MUTED)s;font-weight:500}
.big{font-size:4.6cqw;font-weight:700;line-height:.95;letter-spacing:-.04em}
.big.miss{color:%(MISS)s}
.hd{font-size:1.1cqw;font-weight:500}
.hr{font-size:1.02cqw;color:%(DIM)s}
.split .sb{display:flex;height:1.1cqw;margin:.35cqw 0;background:%(LINE)s}
.split .sb i{display:block;height:100%%}
.split .lg{display:grid;grid-template-columns:1fr 1fr;gap:.15cqw .8cqw;font-size:1.0cqw;color:%(MUTED)s}
.split .lg i{display:inline-block;width:.75cqw;height:.75cqw;margin-right:.4cqw;vertical-align:-.05cqw}
.ty{flex:1;min-height:0}
.ty .chart{object-position:left top}
.say{font-size:1.2cqw;line-height:1.35;border-left:.28cqw solid %(ACCENT)s;padding-left:.8cqw}
.main{display:grid;grid-template-rows:auto minmax(0,1fr) minmax(0,1.05fr);gap:.9cqw;min-height:0}
.kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:1.2cqw}
.kl{font-size:1.0cqw;color:%(MUTED)s}
.kv{font-size:2.1cqw;font-weight:600;letter-spacing:-.02em;line-height:1.1}
.kv small{font-size:1.0cqw;color:%(MUTED)s;font-weight:500;margin-left:.2cqw;letter-spacing:0}
.kd{font-size:1.0cqw}
.ks{font-size:.95cqw;color:%(DIM)s}
.mid{display:grid;grid-template-columns:1.2fr 1fr;gap:1.4cqw;min-height:0}
.bot{display:grid;grid-template-columns:1.5fr 1fr 1fr;gap:1.6cqw;min-height:0}
.pn{display:flex;flex-direction:column;min-height:0;overflow:hidden}
.pt{font-size:1.1cqw;font-weight:600;margin-bottom:.35cqw;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pt span{color:%(MUTED)s;font-weight:400}
.chart{width:100%%;flex:1;min-height:0;display:block;object-fit:contain;object-position:left top}
.row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:.1cqw .8cqw;font-size:1.02cqw;padding:.3cqw 0;border-bottom:.08cqw solid %(LINE)s;align-items:start}
.row .rn{color:%(MUTED)s;white-space:nowrap;text-align:right}
.row .rb{grid-column:1/3;height:.35cqw;background:%(LINE)s}
.row .rb i{display:block;height:100%%;background:%(DOWN)s}
.more{font-size:.95cqw;padding-top:.3cqw}
.tprod{width:100%%;border-collapse:collapse}
.tprod th{font-size:.95cqw;color:%(DIM)s;font-weight:500;text-align:right;padding:0 0 .3cqw .5cqw;border-bottom:.08cqw solid %(LINE)s}
.tprod td{text-align:right;padding:.55cqw 0 .55cqw .5cqw;border-bottom:.08cqw solid %(LINE)s;vertical-align:top;font-size:.95cqw;color:%(MUTED)s}
.tprod td small{display:block}
.tprod td b{display:block;font-size:1.45cqw;font-weight:600;color:%(TEXT)s;line-height:1.1}
.tprod td.g{text-align:left;font-size:1.15cqw;font-weight:600;color:%(TEXT)s;padding-left:0}
.tprod td.g small{display:block;font-size:.92cqw;font-weight:400;color:%(DIM)s;white-space:nowrap}
.tprod{table-layout:fixed}
.tprod th:first-child{width:28%%}
.tprod td small{white-space:normal;line-height:1.25}
.tf{grid-column:1/3;display:flex;flex-wrap:wrap;gap:.3cqw 2.4cqw;font-size:1.02cqw;color:%(MUTED)s;border-top:.1cqw solid %(LINE)s;padding-top:.5cqw}
.tf b{color:%(TEXT)s;font-weight:600}
.tv-empty{grid-column:1/3;display:grid;place-items:center;font-size:2cqw;color:%(MUTED)s}
""" % {"BG": T.BG, "TEXT": T.TEXT, "MUTED": T.MUTED, "DIM": T.DIM, "LINE": T.LINE, "ACCENT": T.ACCENT,
       "MISS": T.MISS, "DOWN": T.DOWN, "F": FONT}

KIOSK_CSS = f"""
header[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],
[data-testid="stStatusWidget"],footer{{display:none!important}}
.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"]{{background:{T.BG}!important}}
[data-testid="stMainBlockContainer"],.block-container{{padding:0!important;max-width:100%!important}}
[data-testid="stVerticalBlock"]{{gap:0!important}}
html,body{{overflow:hidden!important;cursor:none}}
"""


def render(d: TvData, kiosk: bool = False, now: dt.datetime | None = None) -> str:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(WIB)
    mode = "kiosk" if kiosk else "preview"
    css = f"<style>{CSS}{KIOSK_CSS if kiosk else ''}</style>"
    period = PERIOD_LABEL.get(d.period, d.period)
    head = (f'<div class="th"><div><span class="site">{escape(d.site)}</span><span class="per">{period}</span>'
            f'<span class="rng">{escape(d.range_label)}</span></div><div class="clk">{now:%H:%M}</div></div>')
    if d.empty:
        return f'{css}<div class="tv {mode}">{head}<div class="tv-empty">No published data for this site yet.</div></div>'
    k = {x.key: x for x in d.kpis}
    h = d.hero
    pa_t, uoa_t = k["pa"].target, k["uoa"].target
    hero = [f'<div class="when">{escape(h.get("label", ""))}</div>',
            _hero_metric("Use of availability (UoA)", h.get("uoa"), uoa_t, h.get("range_name", ""), h.get("uoa_range")),
            _hero_metric("Physical availability (PA)", h.get("pa"), pa_t, h.get("range_name", ""), h.get("pa_range"))]
    if d.period == "hourly" and h.get("shifts"):
        hero[-1] = hero[-1].replace(
            f'{escape(h.get("range_name", ""))} {pct(h.get("pa_range"))}',
            " · ".join(f"{s} PA {pct(v[0])}" for s, v in h["shifts"].items()))
        hero[-2] = hero[-2].replace(
            f'{escape(h.get("range_name", ""))} {pct(h.get("uoa_range"))}',
            " · ".join(f"{s} UoA {pct(v[1])}" for s, v in h["shifts"].items()))
    hero += [_split_bar(h), f'<div class="pn ty"><div class="hl">PA and hours by type</div>{_type_svg(d, pa_t)}</div>',
             f'<div class="say">{escape(_headline(d, uoa_t))}</div>']
    kp = "".join(_kpi_html(k[x]) for x in ("mtbs", "mttr", "sched", "pm", "ob", "coal"))
    has_plan = d.prod[["ob_plan", "coal_plan"]].notna().any().any() if len(d.prod) else False
    top_c = nice(d.components.iloc[0]["reason"]) if len(d.components) else ""
    upd = d.updated_at.astimezone(WIB).strftime("%d %b %H:%M") if d.updated_at else "—"
    f = d.footer
    return f"""{css}<div class="tv {mode}">{head}
<div class="hero">{''.join(hero)}</div>
<div class="main">
<div class="kpis">{kp}</div>
<div class="mid">
<div class="pn"><div class="pt">PA and UoA, {_title(d)} <span>· open dots = incomplete data</span></div>{_trend_svg(d)}</div>
<div class="pn"><div class="pt">Production, {_title(d)} <span>· {'dashed = plan' if has_plan else 'no plan set'}</span></div>{_prod_svg(d)}</div>
</div>
<div class="bot">
<div class="pn"><div class="pt">Productivity and haul distance <span>· per Ready hour</span></div>{_productivity_html(d)}</div>
<div class="pn"><div class="pt">{escape(top_c + " leads down time" if top_c else "Down time")}</div>{_components_html(d)}</div>
<div class="pn"><div class="pt">Longest down</div>{_units_html(d)}</div>
</div></div>
<div class="tf"><span><b>{f['down_now']}</b> of {f['units']} units down now</span><span>Fuel <b>{n(f['fuel'])} L</b> · <b>{n(f['fuel_ratio'], 2)}</b> L/BCM</span>
<span><b>{n(f['stoppages'])}</b> stoppages</span><span><b>{f['pm_events']}</b> PM events</span>
<span>Approved {upd} · refreshes every 5 min</span></div>
</div>"""
