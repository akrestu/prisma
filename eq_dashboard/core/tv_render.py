"""Render layar TV sebagai HTML + SVG murni (tanpa JavaScript) untuk st.html."""
from __future__ import annotations

import datetime as dt
from html import escape

import pandas as pd

from core.tv import Kpi, TvData

C = {"bg": "#0B0F14", "pn": "#131A23", "ln": "#243040", "tx": "#E8ECF1", "mt": "#93A0B2", "good": "#3FCF8E",
     "bad": "#FF6B5E", "acc": "#F0A63C", "uoa": "#6CB6FF", "R": "#3FCF8E", "I": "#F2C14E", "S": "#7F95C4",
     "D": "#FF6B5E", "track": "#1D2632"}
WIB = dt.timezone(dt.timedelta(hours=7))
BULAN = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
         "November", "Desember"]


def _n(v, d=0) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _kpi_value(k: Kpi) -> tuple[str, str]:
    if k.value is None or pd.isna(k.value):
        return "—", ""
    if k.unit == "%":
        return _n(k.value * 100, 1), "%"
    if k.unit == "jam":
        return _n(k.value, 1), "jam"
    return _n(k.value), k.unit


def _kpi_target(k: Kpi) -> tuple[str, str]:
    if k.key in ("ob", "coal"):
        tgt = f"Plan MTD: {_n(k.target)} {k.unit}" if k.target is not None else "Plan: belum diisi"
    elif k.target is None:
        tgt = "Target: belum ada"
    elif k.unit == "%":
        v = round(k.target * 100, 1)
        tgt = f"Target {_n(v, 0 if v == int(v) else 1)}%"
    else:
        tgt = f"Target {_n(k.target, 0)} {k.unit}"
    if k.status == "none" or k.value is None:
        return tgt, ""
    diff = k.value - k.target
    arrow = "▲" if diff >= 0 else "▼"
    if k.unit == "%":
        delta = f"{arrow} {_n(abs(diff) * 100, 1)} pt"
    elif k.key in ("ob", "coal"):
        delta = f"{arrow} {_n(abs(diff))} ({_n(k.value / k.target * 100, 0)}%)" if k.target else ""
    else:
        delta = f"{arrow} {_n(abs(diff), 1)} {k.unit}"
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
            f'<div class="last">{escape(k.last)}</div></div>')


def _t(x, y, s, size=11, anchor="start", fill=None, weight=None) -> str:
    w = f' font-weight="{weight}"' if weight else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" '
            f'fill="{fill or C["mt"]}"{w}>{escape(str(s))}</text>')


def _trend_svg(d: TvData) -> str:
    df = d.daily.sort_values("date")
    W, H, x0, x1, y0, y1 = 620, 210, 36, 608, 12, 182
    if df.empty:
        return f'<svg viewBox="0 0 {W} {H}"></svg>'
    days = [x.day for x in df["date"]]
    lo, hi = min(days), max(max(days), min(days) + 1)
    X = lambda day: x0 + (day - lo) * (x1 - x0) / (hi - lo)  # noqa: E731
    Y = lambda v: y1 - v * (y1 - y0)  # noqa: E731
    out = []
    for g in (0, .25, .5, .75, 1):
        out.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(g):.1f}" y2="{Y(g):.1f}" stroke="{C["ln"]}"/>')
        out.append(_t(x0 - 6, Y(g) + 4, f"{int(g * 100)}%", 11, "end"))
    if d.uoa_target is not None:
        out.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(d.uoa_target):.1f}" y2="{Y(d.uoa_target):.1f}" '
                   f'stroke="{C["mt"]}" stroke-width="1.5" stroke-dasharray="6 5"/>')
    inc = df[~df["complete"]]
    for day in [x.day for x in inc["date"]]:
        out.append(f'<rect x="{X(day) - 8:.1f}" y="{y0}" width="16" height="{y1 - y0}" fill="#FFFFFF" fill-opacity=".06"/>')
    if len(inc):
        out.append(_t(x1 - 2, y0 + 12, f"{', '.join(str(x.day) for x in inc['date'])} belum lengkap", 10.5, "end"))
    for col, color in (("PA", C["acc"]), ("UoA", C["uoa"])):
        comp = df[df["complete"]]
        if len(comp) > 1:
            pts = " ".join(f"{X(x.day):.1f},{Y(v):.1f}" for x, v in zip(comp["date"], comp[col]))
            out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="3" stroke-linejoin="round"/>')
        for x, v, ok in zip(df["date"], df[col], df["complete"]):
            if not ok and pd.notna(v):
                out.append(f'<circle cx="{X(x.day):.1f}" cy="{Y(v):.1f}" r="4" fill="{C["bg"]}" stroke="{color}" stroke-width="2"/>')
        if len(comp):
            lx, lv = comp["date"].iloc[-1], comp[col].iloc[-1]
            out.append(f'<circle cx="{X(lx.day):.1f}" cy="{Y(lv):.1f}" r="5" fill="{color}"/>')
            out.append(_t(X(lx.day) - 8, Y(lv) - 9, f"{_n(lv * 100, 1)}%", 12, "end", color, 600))
    step = 1 if hi - lo <= 12 else 2
    for day in days:
        if (day - lo) % step == 0 or day == days[-1]:
            out.append(_t(X(day), y1 + 16, day, 11, "middle"))
    return f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">{"".join(out)}</svg>'


def _bars(out, vals, plans, x0, x1, ya, yb, color, label, fmt):
    n = max(len(vals), 1)
    top = max([*vals, *[p for p in plans if pd.notna(p)], 1]) * 1.1
    bw = (x1 - x0) / n
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


def _prod_svg(d: TvData) -> str:
    p = d.prod
    W, H = 500, 210
    if p.empty:
        return f'<svg viewBox="0 0 {W} {H}">{_t(250, 105, "Belum ada data produksi", 13, "middle")}</svg>'
    out = []
    k = lambda v: (_n(v / 1000, 0 if v >= 10000 else 1) + "rb") if v else "0"  # noqa: E731
    bw = _bars(out, p["ob"].tolist(), p["ob_plan"].tolist(), 46, 494, 18, 98, C["acc"], "OB (BCM)", k)
    _bars(out, p["coal"].tolist(), p["coal_plan"].tolist(), 46, 494, 122, 192, C["uoa"], "Coal (ton)", k)
    days = [x.day for x in p["date"]]
    for i, day in enumerate(days):
        if i == 0 or i == len(days) - 1 or day % 5 == 0:
            out.append(_t(46 + (i + .5) * bw, 206, day, 10.5, "middle"))
    return f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">{"".join(out)}</svg>'


SHORT_TYPE = {"Supporting Equipment": "Suppt. Equipment"}


def _type_label(t) -> str:
    t = str(t)
    return SHORT_TYPE.get(t, t if len(t) <= 17 else t[:16] + "…")


def _type_svg(d: TvData, pa_target) -> str:
    bt = d.by_type.head(7)
    W, H, lx, x1, rh = 300, 190, 118, 258, 26
    out = []
    for i, r in enumerate(bt.itertuples()):
        y = 6 + i * rh
        out.append(_t(lx - 6, y + 15, _type_label(r.type), 11.5, "end", C["tx"]))
        out.append(f'<rect x="{lx}" y="{y + 4}" width="{x1 - lx}" height="14" fill="{C["track"]}"/>')
        col = C["acc"] if pa_target is None else (C["good"] if r.PA >= pa_target else C["bad"])
        out.append(f'<rect x="{lx}" y="{y + 4}" width="{(x1 - lx) * (r.PA if pd.notna(r.PA) else 0):.1f}" height="14" fill="{col}"/>')
        out.append(_t(x1 + 6, y + 15, f"{_n(r.PA * 100, 1)}%", 11.5, fill=C["tx"], weight=600))
    if pa_target is not None:
        tx = lx + (x1 - lx) * pa_target
        out.append(f'<line x1="{tx:.1f}" x2="{tx:.1f}" y1="4" y2="{6 + len(bt) * rh}" stroke="{C["tx"]}" stroke-dasharray="3 3"/>')
    return f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">{"".join(out)}</svg>'


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
    return f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">{"".join(out)}</svg>'


def _components_html(d: TvData) -> str:
    if d.components.empty:
        return '<div class="tlist"><span class="m">Tidak ada jam down.</span></div>'
    top = d.components["hours"].max()
    rows = "".join(f'<div class="r"><span>{escape(str(r.reason).title())}</span><span class="n">{_n(r.hours)}</span>'
                   f'<div class="b"><i style="width:{r.hours / top * 100:.1f}%"></i></div></div>'
                   for r in d.components.itertuples())
    return f'<div class="tlist">{rows}</div>'


def _units_html(d: TvData) -> str:
    bu = d.bad_units
    if bu.empty:
        return '<table class="tunits"><tr><td class="m">Tidak ada unit down.</td></tr></table>'
    rows = []
    for r in bu.head(4).itertuples():
        badge = ('<span class="badge">down sebulan</span>' if r.full_period else
                 ('<span class="badge">sedang down</span>' if r.down_now else ""))
        rows.append(f'<tr><td><span class="u">{escape(r.unit)}</span> <span class="m">{escape(str(r.model or ""))}</span><br>'
                    f'<span class="m">{escape(str(r.reason or "").title())}</span></td>'
                    f'<td class="n">{_n(r.hours)} j<br>{badge}</td></tr>')
    rest = len(bu) - 4
    if rest > 0:
        names = ", ".join(escape(u) for u in bu["unit"].iloc[4:])
        rows.append(f'<tr><td colspan="2" class="m" style="border-bottom:0">+ {rest} unit lain ({names})</td></tr>')
    return f'<table class="tunits">{"".join(rows)}</table>'


CSS = """
.tv{container-type:inline-size;background:%(bg)s;color:%(tx)s;font-family:"IBM Plex Sans","Segoe UI",Roboto,sans-serif;
 display:grid;grid-template-rows:auto auto minmax(0,1.15fr) minmax(0,1fr) auto;gap:.7cqw;padding:1cqw;overflow:hidden;
 box-sizing:border-box;border-radius:6px}
.tv.preview{aspect-ratio:16/9;width:100%%}
.tv.kiosk{width:100vw;height:100vh;border-radius:0}
.tv *{min-width:0;box-sizing:border-box}
.tv-h{display:flex;justify-content:space-between;align-items:flex-end;gap:1cqw;border-bottom:.1cqw solid %(ln)s;padding-bottom:.5cqw}
.tv-h .site{font-family:"Barlow Condensed","Arial Narrow",sans-serif;font-weight:700;font-size:2.6cqw;line-height:1}
.tv-h .sub{font-size:1cqw;color:%(mt)s}
.tv-h .right{text-align:right;font-family:Consolas,monospace;font-size:.85cqw;color:%(mt)s;display:grid;gap:.2cqw}
.tv-h .clock{font-size:1.9cqw;color:%(tx)s;font-family:"Barlow Condensed",sans-serif;font-weight:600}
.tv-kpis{display:grid;grid-template-columns:repeat(8,1fr);gap:.6cqw}
.tk{background:%(pn)s;border:.08cqw solid %(ln)s;border-top:.3cqw solid;border-radius:.4cqw;padding:.55cqw .7cqw;display:grid;gap:.15cqw;align-content:start}
.tk .l{font-size:.85cqw;color:%(mt)s;text-transform:uppercase;letter-spacing:.06em;font-family:Consolas,monospace}
.tk .v{font-family:"Barlow Condensed","Arial Narrow",sans-serif;font-weight:700;font-size:2.7cqw;line-height:1}
.tk .v small{font-size:1.1cqw;font-weight:500;color:%(mt)s;margin-left:.2cqw}
.tk .t{font-size:.8cqw;color:%(mt)s}
.tk .dlt{font-family:Consolas,monospace;font-size:.85cqw;font-weight:600}
.tk .last{font-family:Consolas,monospace;font-size:.78cqw;color:%(mt)s;border-top:.08cqw solid %(ln)s;padding-top:.25cqw}
.tv-mid{display:grid;grid-template-columns:1.25fr 1fr;gap:.6cqw}
.tv-bot{display:grid;grid-template-columns:1fr 1.1fr 1fr 1.15fr;gap:.6cqw}
.tp{background:%(pn)s;border:.08cqw solid %(ln)s;border-radius:.4cqw;padding:.55cqw .7cqw;display:flex;flex-direction:column;gap:.3cqw;overflow:hidden}
.tp h4{margin:0;font-family:Consolas,monospace;font-weight:500;font-size:.85cqw;letter-spacing:.06em;text-transform:uppercase;color:%(mt)s;display:flex;justify-content:space-between;gap:.5cqw;padding:0}
.tp h4 span{text-transform:none;letter-spacing:0}
.tp svg{width:100%%;flex:1;min-height:0;display:block;font-family:Consolas,monospace}
.tlist{display:grid;gap:.35cqw;font-size:.9cqw}
.tlist .r{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:.1cqw .5cqw;align-items:center}
.tlist .n{font-family:Consolas,monospace}
.tlist .b{grid-column:1/-1;height:.45cqw;background:%(track)s;border-radius:.2cqw;overflow:hidden}
.tlist .b i{display:block;height:100%%;background:%(D)s}
.tunits{width:100%%;border-collapse:collapse;font-size:.85cqw}
.tunits td{padding:.28cqw .2cqw;border:0;border-bottom:.08cqw solid %(ln)s;vertical-align:middle;text-align:left;color:%(tx)s;background:none}
.tunits td.n{font-family:Consolas,monospace;text-align:right;white-space:nowrap}
.tunits .u{font-family:Consolas,monospace;font-weight:600}
.m{color:%(mt)s}
.badge{display:inline-block;font-family:Consolas,monospace;font-size:.7cqw;padding:.05cqw .4cqw;border-radius:.2cqw;background:rgba(255,107,94,.16);color:%(bad)s;white-space:nowrap}
.tv-f{display:flex;flex-wrap:wrap;gap:.4cqw 1.6cqw;font-family:Consolas,monospace;font-size:.85cqw;color:%(mt)s;border-top:.1cqw solid %(ln)s;padding-top:.45cqw}
.tv-f b{color:%(tx)s;font-weight:600}
.tlegend{display:flex;gap:.9cqw;font-size:.75cqw;flex-wrap:wrap}
.tlegend i{display:inline-block;width:.8cqw;height:.3cqw;margin-right:.3cqw;vertical-align:middle}
.tv-empty{display:grid;place-items:center;font-size:2cqw;color:%(mt)s;text-align:center}
""" % C

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
    if d.empty:
        return (f'{css}<div class="tv {mode}"><div class="tv-h"><div class="site">{site}</div>'
                f'<div class="right"><div class="clock">{now:%H:%M}</div></div></div>'
                f'<div class="tv-empty" style="grid-row:2/6">Belum ada data yang dipublikasikan untuk site ini.</div></div>')
    month = f"{BULAN[d.month.month]} {d.month.year}"
    upd = d.updated_at.astimezone(WIB).strftime("%d %b %Y %H:%M") if d.updated_at else "—"
    lc = f"{d.last_complete:%d %b}" if d.last_complete else "—"
    pa_target = next((k.target for k in d.kpis if k.key == "pa"), None)
    f = d.footer
    legend_t = (f'<span><i style="background:{C["acc"]}"></i>PA</span><span><i style="background:{C["uoa"]}"></i>UoA</span>'
                + (f'<span><i style="background:{C["mt"]}"></i>target UoA {_n(d.uoa_target * 100, 0)}%</span>'
                   if d.uoa_target is not None else ""))
    has_plan = d.prod[["ob_plan", "coal_plan"]].notna().any().any() if len(d.prod) else False
    legend_d = "".join(f'<span><i style="background:{C[x]}"></i>{x}</span>' for x in "RISD")
    return f"""{css}<div class="tv {mode}">
<div class="tv-h"><div><div class="site">{site}</div>
<div class="sub">Kinerja Alat &amp; Produksi · {month} · MTD {d.first_date:%d}–{d.last_date:%d %b}</div></div>
<div class="right"><div class="clock">{now:%H:%M}</div>
<div>Data terakhir: {d.last_date:%d %b %Y} · hari lengkap terakhir: {lc}</div>
<div><span style="color:{C['good']}">● PUBLISHED</span> · disetujui {upd} · diperbarui otomatis tiap 5 menit</div></div></div>
<div class="tv-kpis">{''.join(_kpi_html(k) for k in d.kpis)}</div>
<div class="tv-mid">
<div class="tp"><h4>Trend harian PA &amp; UoA <span class="tlegend">{legend_t}</span></h4>{_trend_svg(d)}</div>
<div class="tp"><h4>Produksi harian <span>{'garis putus = plan' if has_plan else 'plan belum diisi'}</span></h4>{_prod_svg(d)}</div>
</div>
<div class="tv-bot">
<div class="tp"><h4>PA per Type <span>MTD</span></h4>{_type_svg(d, pa_target)}</div>
<div class="tp"><h4>Time distribution <span class="tlegend">{legend_d}</span></h4>{_dist_svg(d)}</div>
<div class="tp"><h4>Komponen down terbesar <span>jam</span></h4>{_components_html(d)}</div>
<div class="tp"><h4>Unit bermasalah <span>jam down MTD</span></h4>{_units_html(d)}</div>
</div>
<div class="tv-f"><span><b>{f['units']}</b> unit aktif</span><span><b>{f['down_now']}</b> unit down pada data terakhir</span>
<span>Fuel MTD <b>{_n(f['fuel'])} L</b></span><span>Fuel ratio <b>{_n(f['fuel_ratio'], 2)} L/BCM</b></span>
<span>Stoppage MTD <b>{_n(f['stoppages'])}</b></span><span>PM MTD <b>{f['pm_events']}</b></span>
<span>Waktu layar {now:%d %b %H:%M} WIB</span></div>
</div>"""
