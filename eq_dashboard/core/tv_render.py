"""Render the TV screen as HTML + SVG (no JavaScript) for st.html.

Charts are SVG images (<img src="data:image/svg+xml;base64,...">) because st.html sanitises inline <svg>.
One font family everywhere: IBM Plex Sans, self-hosted (/app/static/fonts) and embedded inside chart SVGs.
"""
from __future__ import annotations

import base64
import datetime as dt
from functools import lru_cache
from html import escape
from pathlib import Path

import pandas as pd

from core.periods import PERIOD_LABEL
from core.tv import Kpi, TvData

C = {"bg": "#0B0F14", "pn": "#131A23", "ln": "#243040", "tx": "#E8ECF1", "mt": "#93A0B2", "good": "#3FCF8E",
     "bad": "#FF6B5E", "acc": "#F0A63C", "uoa": "#6CB6FF", "R": "#3FCF8E", "I": "#F2C14E", "S": "#7F95C4",
     "D": "#FF6B5E", "track": "#1D2632"}
WIB = dt.timezone(dt.timedelta(hours=7))
FONT = "'IBM Plex Sans', 'Segoe UI', Roboto, Arial, sans-serif"
FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
SHORT_TYPE = {"Supporting Equipment": "Suppt. Equipment"}


@lru_cache(maxsize=1)
def _font_face_svg() -> str:
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


def _svg(w: int, h: int, body: str) -> str:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet" '
           f'font-family="{FONT}">{_font_face_svg()}{body}</svg>')
    return f'<img class="chart" alt="" src="data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}">'


def _t(x, y, s, size=11, anchor="start", fill=None, weight=None) -> str:
    w = f' font-weight="{weight}"' if weight else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" '
            f'fill="{fill or C["mt"]}"{w}>{escape(str(s))}</text>')


# ------------------------------------------------------------------ KPI cards
def _kpi_value(k: Kpi) -> tuple[str, str]:
    if k.value is None or pd.isna(k.value):
        return "—", ""
    if k.unit == "%":
        return n(k.value * 100, 1), "%"
    if k.unit == "h":
        return n(k.value, 1), "h"
    return n(k.value), k.unit


def _kpi_target(k: Kpi) -> tuple[str, str]:
    if k.key in ("ob", "coal"):
        tgt = f"Plan: {n(k.target)} {k.unit}" if k.target is not None else "Plan: not set"
    elif k.target is None:
        tgt = "Target: not set"
    elif k.unit == "%":
        v = round(k.target * 100, 1)
        tgt = f"Target {n(v, 0 if v == int(v) else 1)}%"
    else:
        tgt = f"Target {n(k.target, 0)} {k.unit}"
    if k.status == "none" or k.value is None:
        return tgt, ""
    diff = k.value - k.target
    arrow = "▲" if diff >= 0 else "▼"
    if k.unit == "%":
        delta = f"{arrow} {n(abs(diff) * 100, 1)} pt"
    elif k.key in ("ob", "coal"):
        delta = f"{arrow} {n(abs(diff))} ({n(k.value / k.target * 100, 0)}%)" if k.target else ""
    else:
        delta = f"{arrow} {n(abs(diff), 1)} {k.unit}"
    return tgt, delta


def _kpi_html(k: Kpi) -> str:
    val, unit = _kpi_value(k)
    tgt, delta = _kpi_target(k)
    color = C[k.status] if k.status in ("good", "bad") else "#3A4656"
    dcol = C[k.status] if k.status in ("good", "bad") else C["mt"]
    note = (f'<div class="dlt" style="color:{C["mt"]}">{escape(k.note)}</div>'
            if k.note and k.key not in ("ob", "coal") else "")
    dl = f'<div class="dlt" style="color:{dcol}">{delta}</div>' if delta else ""
    return (f'<div class="tk" style="border-top-color:{color}"><div class="l">{escape(k.label)}</div>'
            f'<div class="v">{val}<small>{unit}</small></div><div class="t">{escape(tgt)}</div>{dl}{note}'
            f'<div class="last">{escape(k.sub)}</div></div>')


# ------------------------------------------------------------------ charts
def _xlabels(labels: list[str], x_of, y: float, max_labels: int = 12) -> list[str]:
    step = max(1, -(-len(labels) // max_labels))
    last = len(labels) - 1
    keep = [i for i in range(len(labels)) if i % step == 0]
    if keep and last - keep[-1] >= step:  # add the last label only when it does not collide
        keep.append(last)
    return [_t(x_of(i), y, labels[i], 11, "middle") for i in keep]


def _trend_svg(d: TvData) -> str:
    df = d.trend
    W, H, x0, x1, y0, y1 = 620, 210, 38, 606, 12, 182
    if df.empty:
        return _svg(W, H, "")
    k = len(df)
    X = (lambda i: (x0 + x1) / 2) if k == 1 else (lambda i: x0 + i * (x1 - x0) / (k - 1))
    Y = lambda v: y1 - v * (y1 - y0)  # noqa: E731
    out = []
    for g in (0, .25, .5, .75, 1):
        out.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(g):.1f}" y2="{Y(g):.1f}" stroke="{C["ln"]}"/>')
        out.append(_t(x0 - 6, Y(g) + 4, f"{int(g * 100)}%", 11, "end"))
    if d.uoa_target is not None:
        out.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(d.uoa_target):.1f}" y2="{Y(d.uoa_target):.1f}" '
                   f'stroke="{C["mt"]}" stroke-width="1.5" stroke-dasharray="6 5"/>')
    inc = [i for i, ok in enumerate(df["complete"]) if not ok]
    for i in inc:
        out.append(f'<rect x="{X(i) - 8:.1f}" y="{y0}" width="16" height="{y1 - y0}" fill="#FFFFFF" fill-opacity=".06"/>')
    if inc:
        out.append(_t(x1 - 2, y0 + 12, f"{', '.join(df['label'].iloc[i] for i in inc)} incomplete", 10.5, "end"))
    for col, color in (("PA", C["acc"]), ("UoA", C["uoa"])):
        pts = [(X(i), Y(v)) for i, (v, ok) in enumerate(zip(df[col], df["complete"])) if ok and pd.notna(v)]
        if len(pts) > 1:
            out.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" fill="none" '
                       f'stroke="{color}" stroke-width="3" stroke-linejoin="round"/>')
        for i, (v, ok) in enumerate(zip(df[col], df["complete"])):
            if pd.notna(v) and (not ok or k <= 12):
                fill = color if ok else C["bg"]
                out.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="4" fill="{fill}" stroke="{color}" stroke-width="2"/>')
        if pts:
            a, b = pts[-1]
            v = [v for v, ok in zip(df[col], df["complete"]) if ok and pd.notna(v)][-1]
            out.append(_t(a - 8 if k > 1 else a + 10, b - 9, f"{v * 100:.1f}%", 12, "end" if k > 1 else "start",
                          color, 600))
    out += _xlabels(list(df["label"]), X, y1 + 16)
    return _svg(W, H, "".join(out))


def _bars(out, vals, plans, x0, x1, ya, yb, color, label, fmt):
    k = max(len(vals), 1)
    top = max([*vals, *[p for p in plans if pd.notna(p)], 1]) * 1.1
    bw = (x1 - x0) / k
    Y = lambda v: yb - v / top * (yb - ya)  # noqa: E731
    for g in (0, .5, 1):
        out.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(top * g / 1.1):.1f}" y2="{Y(top * g / 1.1):.1f}" stroke="{C["ln"]}"/>')
        out.append(_t(x0 - 5, Y(top * g / 1.1) + 4, fmt(top * g / 1.1), 10.5, "end"))
    for i, v in enumerate(vals):
        out.append(f'<rect x="{x0 + i * bw + 1.5:.1f}" y="{Y(v):.1f}" width="{max(bw - 3, 1):.1f}" '
                   f'height="{yb - Y(v):.1f}" fill="{color}"/>')
    if any(pd.notna(p) for p in plans):
        pts = " ".join(f"{x0 + (i + .5) * bw:.1f},{Y(p):.1f}" for i, p in enumerate(plans) if pd.notna(p))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{C["tx"]}" stroke-width="2" stroke-dasharray="4 4"/>')
    out.append(_t(x0, ya - 3, label, 11, fill=C["tx"]))
    return bw


def _short(v: float) -> str:
    if not v:
        return "0"
    return f"{v / 1000:,.0f}k" if v >= 10000 else (f"{v / 1000:,.1f}k" if v >= 1000 else f"{v:,.0f}")


def _prod_svg(d: TvData) -> str:
    p = d.prod
    W, H = 500, 210
    if p.empty:
        return _svg(W, H, _t(250, 105, "No production data", 13, "middle"))
    out = []
    bw = _bars(out, p["ob"].tolist(), p["ob_plan"].tolist(), 46, 494, 18, 98, C["acc"], "OB (BCM)", _short)
    _bars(out, p["coal"].tolist(), p["coal_plan"].tolist(), 46, 494, 122, 192, C["uoa"], "Coal (t)", _short)
    out += _xlabels(list(p["label"]), lambda i: 46 + (i + .5) * bw, 206, 8)
    return _svg(W, H, "".join(out))


def _type_label(t) -> str:
    t = str(t)
    return SHORT_TYPE.get(t, t if len(t) <= 17 else t[:16] + "…")


def _type_svg(d: TvData, pa_target) -> str:
    bt = d.by_type.head(7)
    W, H, lx, x1, rh = 300, 190, 118, 246, 26
    out = []
    for i, r in enumerate(bt.itertuples()):
        y = 6 + i * rh
        out.append(_t(lx - 6, y + 15, _type_label(r.type), 11.5, "end", C["tx"]))
        out.append(f'<rect x="{lx}" y="{y + 4}" width="{x1 - lx}" height="14" fill="{C["track"]}"/>')
        col = C["acc"] if pa_target is None else (C["good"] if r.PA >= pa_target else C["bad"])
        out.append(f'<rect x="{lx}" y="{y + 4}" width="{(x1 - lx) * (r.PA if pd.notna(r.PA) else 0):.1f}" height="14" fill="{col}"/>')
        out.append(_t(x1 + 6, y + 15, f"{r.PA * 100:.1f}%", 11.5, fill=C["tx"], weight=600))
    if pa_target is not None:
        tx = lx + (x1 - lx) * pa_target
        out.append(f'<line x1="{tx:.1f}" x2="{tx:.1f}" y1="4" y2="{6 + len(bt) * rh}" stroke="{C["tx"]}" stroke-dasharray="3 3"/>')
    return _svg(W, H, "".join(out))


def _dist_svg(d: TvData) -> str:
    bt = d.by_type.head(7)
    W, H, lx, x1, rh = 320, 190, 118, 316, 26
    out = []
    for i, r in enumerate(bt.itertuples()):
        y, x = 6 + i * rh, lx
        out.append(_t(lx - 6, y + 15, _type_label(r.type), 11.5, "end", C["tx"]))
        for j, (v, c) in enumerate(((r.Rp, C["R"]), (r.Ip, C["I"]), (r.Sp, C["S"]), (r.Dp, C["D"]))):
            w = (x1 - lx) * (v if pd.notna(v) else 0)
            out.append(f'<rect x="{x:.1f}" y="{y + 4}" width="{max(w - 1, 0):.1f}" height="14" fill="{c}"/>')
            if j == 3 and w > 26:
                out.append(_t(x + w - 4, y + 15, f"{round(v * 100)}%", 10.5, "end", C["bg"], 600))
            x += w
    return _svg(W, H, "".join(out))


# ------------------------------------------------------------------ HTML panels
def _productivity_html(d: TvData) -> str:
    rows = []
    for grp, unit, label in (("OB", "BCM", "OB"), ("CG", "t", "Coal (CG)")):
        p = d.productivity.get(grp) or {}
        if not p or not p.get("volume"):
            rows.append(f'<tr class="hd"><td colspan="4">{label} <span class="m">· no trips</span></td></tr>')
            continue
        rows.append(f'<tr class="hd"><td colspan="4">{label} <span class="m">· {p["loaders"]} loaders · '
                    f'{p["haulers"]} haulers · {n(p["volume"])} {unit}</span></td></tr>')
        rows.append(
            f'<tr><td class="n"><b>{n(p["loader_per_hour"])}</b><br><span class="m">{unit}/h per loader</span></td>'
            f'<td class="n"><b>{n(p["hauler_per_hour"], 1)}</b><br><span class="m">{unit}/h per hauler '
            f'({n(p["rit_per_hour"], 2)} trips/h)</span></td>'
            f'<td class="n"><b>{n(p["dist_h"])}</b><br><span class="m">m horizontal</span></td>'
            f'<td class="n"><b>{n(p["dist_v"])}</b><br><span class="m">m vertical</span></td></tr>')
    return f'<table class="tprod">{"".join(rows)}</table>'


def _components_html(d: TvData) -> str:
    if d.components.empty:
        return '<div class="tlist"><span class="m">No down hours.</span></div>'
    top = d.components["hours"].max()
    rows = "".join(f'<div class="r"><span>{escape(str(r.reason).title())}</span><span class="n">{n(r.hours)}</span>'
                   f'<div class="b"><i style="width:{r.hours / top * 100:.1f}%"></i></div></div>'
                   for r in d.components.itertuples())
    return f'<div class="tlist">{rows}</div>'


def _units_html(d: TvData) -> str:
    bu = d.bad_units
    if bu.empty:
        return '<table class="tunits"><tr><td class="m">No units down.</td></tr></table>'
    rows = []
    for r in bu.head(3).itertuples():
        badge = ('<span class="badge">down all period</span>' if r.full_period else
                 ('<span class="badge">down now</span>' if r.down_now else ""))
        rows.append(f'<tr><td><span class="u">{escape(r.unit)}</span> <span class="m">{escape(str(r.model or ""))}</span><br>'
                    f'<span class="m">{escape(str(r.reason or "").title())}</span></td>'
                    f'<td class="n">{n(r.hours)} h<br>{badge}</td></tr>')
    rest = len(bu) - 3
    if rest > 0:
        names = ", ".join(escape(u) for u in bu["unit"].iloc[3:])
        rows.append(f'<tr><td colspan="2" class="m" style="border-bottom:0">+ {rest} more ({names})</td></tr>')
    return f'<table class="tunits">{"".join(rows)}</table>'


CSS = """
@font-face{font-family:'IBM Plex Sans';font-weight:400;src:url(/app/static/fonts/ibm-plex-sans-400.woff2) format('woff2')}
@font-face{font-family:'IBM Plex Sans';font-weight:500;src:url(/app/static/fonts/ibm-plex-sans-500.woff2) format('woff2')}
@font-face{font-family:'IBM Plex Sans';font-weight:600;src:url(/app/static/fonts/ibm-plex-sans-600.woff2) format('woff2')}
@font-face{font-family:'IBM Plex Sans';font-weight:700;src:url(/app/static/fonts/ibm-plex-sans-700.woff2) format('woff2')}
.tv{container-type:inline-size;background:%(bg)s;color:%(tx)s;font-family:%(font)s;font-variant-numeric:tabular-nums;
 display:grid;grid-template-rows:auto auto minmax(0,1.15fr) minmax(0,1fr) auto;gap:.7cqw;padding:1cqw;overflow:hidden;
 box-sizing:border-box;border-radius:6px}
.tv.preview{aspect-ratio:16/9;width:100%%}
.tv.kiosk{width:min(100vw,177.78vh);height:min(100vh,56.25vw);margin:0 auto;border-radius:0}
.tv *{min-width:0;box-sizing:border-box;font-family:%(font)s}
.tv-h{display:flex;justify-content:space-between;align-items:flex-end;gap:1cqw;border-bottom:.1cqw solid %(ln)s;padding-bottom:.5cqw}
.tv-h .site{font-weight:700;font-size:2.4cqw;line-height:1;letter-spacing:-.01em}
.tv-h .period{display:inline-block;margin-left:.8cqw;padding:.15cqw .6cqw;border-radius:.3cqw;background:%(acc)s;color:%(bg)s;
 font-size:.9cqw;font-weight:600;vertical-align:.4cqw;letter-spacing:.04em;text-transform:uppercase}
.tv-h .sub{font-size:1cqw;color:%(mt)s;margin-top:.3cqw}
.tv-h .right{text-align:right;font-size:.85cqw;color:%(mt)s;display:grid;gap:.2cqw}
.tv-h .clock{font-size:1.9cqw;color:%(tx)s;font-weight:600}
.tv-kpis{display:grid;grid-template-columns:repeat(8,1fr);gap:.6cqw}
.tk{background:%(pn)s;border:.08cqw solid %(ln)s;border-top:.3cqw solid;border-radius:.4cqw;padding:.55cqw .7cqw;display:grid;gap:.15cqw;align-content:start}
.tk .l{font-size:.8cqw;color:%(mt)s;text-transform:uppercase;letter-spacing:.06em;font-weight:500}
.tk .v{font-weight:700;font-size:2.4cqw;line-height:1.05;letter-spacing:-.02em}
.tk .v small{font-size:1cqw;font-weight:500;color:%(mt)s;margin-left:.2cqw;letter-spacing:0}
.tk .t{font-size:.8cqw;color:%(mt)s}
.tk .dlt{font-size:.85cqw;font-weight:600}
.tk .last{font-size:.78cqw;color:%(mt)s;border-top:.08cqw solid %(ln)s;padding-top:.25cqw}
.tv-mid{display:grid;grid-template-columns:1.15fr 1fr 1.05fr;gap:.6cqw}
.tv-bot{display:grid;grid-template-columns:1fr 1.1fr 1fr 1.15fr;gap:.6cqw}
.tp{background:%(pn)s;border:.08cqw solid %(ln)s;border-radius:.4cqw;padding:.55cqw .7cqw;display:flex;flex-direction:column;gap:.3cqw;overflow:hidden}
.tp h4{margin:0;padding:0;font-weight:500;font-size:.8cqw;letter-spacing:.06em;text-transform:uppercase;color:%(mt)s;display:flex;justify-content:space-between;gap:.5cqw}
.tp h4 span{text-transform:none;letter-spacing:0}
.tp .chart{width:100%%;flex:1;min-height:0;display:block;object-fit:contain}
.tlist{display:grid;gap:.35cqw;font-size:.9cqw}
.tlist .r{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:.1cqw .5cqw;align-items:center}
.tlist .b{grid-column:1/-1;height:.45cqw;background:%(track)s;border-radius:.2cqw;overflow:hidden}
.tlist .b i{display:block;height:100%%;background:%(D)s}
.tunits,.tprod{width:100%%;border-collapse:collapse;font-size:.85cqw}
.tunits td,.tprod td{padding:.28cqw .2cqw;border:0;border-bottom:.08cqw solid %(ln)s;vertical-align:middle;text-align:left;color:%(tx)s;background:none}
.tprod{height:100%%}
.tprod td{padding:.35cqw .3cqw}
.tprod td b{font-size:1.5cqw;font-weight:700}
.tprod tr.hd td{font-weight:600;font-size:.95cqw;border-bottom:0;padding-bottom:0;text-align:left}
.tunits td.n,.tprod td.n{text-align:right;white-space:nowrap}
.tunits .u{font-weight:600}
.m{color:%(mt)s;font-size:.8cqw}
.badge{display:inline-block;font-size:.7cqw;padding:.05cqw .4cqw;border-radius:.2cqw;background:rgba(255,107,94,.16);color:%(bad)s;white-space:nowrap}
.tv-f{display:flex;flex-wrap:wrap;gap:.4cqw 1.6cqw;font-size:.85cqw;color:%(mt)s;border-top:.1cqw solid %(ln)s;padding-top:.45cqw}
.tv-f b{color:%(tx)s;font-weight:600}
.tlegend{display:flex;gap:.9cqw;font-size:.75cqw;flex-wrap:wrap}
.tlegend i{display:inline-block;width:.8cqw;height:.3cqw;margin-right:.3cqw;vertical-align:middle}
.tv-empty{display:grid;place-items:center;font-size:2cqw;color:%(mt)s;text-align:center}
""" % {**C, "font": FONT}

KIOSK_CSS = """
header[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],
[data-testid="stStatusWidget"],footer{display:none!important}
.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"]{background:#0B0F14!important}
[data-testid="stMainBlockContainer"],.block-container{padding:0!important;max-width:100%!important}
[data-testid="stVerticalBlock"]{gap:0!important}
html,body{overflow:hidden!important;cursor:none}
"""


def render(d: TvData, kiosk: bool = False, now: dt.datetime | None = None) -> str:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(WIB)
    mode = "kiosk" if kiosk else "preview"
    css = f"<style>{CSS}{KIOSK_CSS if kiosk else ''}</style>"
    site = escape(d.site)
    period = PERIOD_LABEL.get(d.period, d.period)
    if d.empty:
        return (f'{css}<div class="tv {mode}"><div class="tv-h"><div class="site">{site}'
                f'<span class="period">{period}</span></div>'
                f'<div class="right"><div class="clock">{now:%H:%M}</div></div></div>'
                f'<div class="tv-empty" style="grid-row:2/6">No published data for this site yet.</div></div>')
    upd = d.updated_at.astimezone(WIB).strftime("%d %b %Y %H:%M") if d.updated_at else "—"
    lc = f"{d.last_complete:%d %b}" if d.last_complete else "—"
    pa_target = next((k.target for k in d.kpis if k.key == "pa"), None)
    f = d.footer
    legend_t = (f'<span><i style="background:{C["acc"]}"></i>PA</span><span><i style="background:{C["uoa"]}"></i>UoA</span>'
                + (f'<span><i style="background:{C["mt"]}"></i>UoA target {n(d.uoa_target * 100, 0)}%</span>'
                   if d.uoa_target is not None else ""))
    has_plan = d.prod[["ob_plan", "coal_plan"]].notna().any().any() if len(d.prod) else False
    legend_d = "".join(f'<span><i style="background:{C[x]}"></i>{x}</span>' for x in "RISD")
    return f"""{css}<div class="tv {mode}">
<div class="tv-h"><div><div class="site">{site}<span class="period">{period}</span></div>
<div class="sub">Equipment &amp; Production Performance · {escape(d.range_label)}</div></div>
<div class="right"><div class="clock">{now:%H:%M}</div>
<div>Latest data: {d.last_date:%d %b %Y} · last complete day: {lc}</div>
<div><span style="color:{C['good']}">● PUBLISHED</span> · approved {upd} · auto-refresh every 5 min</div></div></div>
<div class="tv-kpis">{''.join(_kpi_html(k) for k in d.kpis)}</div>
<div class="tv-mid">
<div class="tp"><h4>PA &amp; UoA trend <span class="tlegend">{legend_t}</span></h4>{_trend_svg(d)}</div>
<div class="tp"><h4>Production <span>{'dashed line = plan' if has_plan else 'no plan set'}</span></h4>{_prod_svg(d)}</div>
<div class="tp"><h4>Productivity &amp; haul distance <span>per Ready hour, trip-weighted</span></h4>{_productivity_html(d)}</div>
</div>
<div class="tv-bot">
<div class="tp"><h4>PA by type</h4>{_type_svg(d, pa_target)}</div>
<div class="tp"><h4>Time distribution <span class="tlegend">{legend_d}</span></h4>{_dist_svg(d)}</div>
<div class="tp"><h4>Top down components <span>hours</span></h4>{_components_html(d)}</div>
<div class="tp"><h4>Problem units <span>down hours</span></h4>{_units_html(d)}</div>
</div>
<div class="tv-f"><span><b>{f['units']}</b> active units</span><span><b>{f['down_now']}</b> units down at latest record</span>
<span>Fuel <b>{n(f['fuel'])} L</b></span><span>Fuel ratio <b>{n(f['fuel_ratio'], 2)} L/BCM</b></span>
<span>Stoppages <b>{n(f['stoppages'])}</b></span><span>PM events <b>{f['pm_events']}</b></span>
<span>Screen time {now:%d %b %H:%M} WIB</span></div>
</div>"""
