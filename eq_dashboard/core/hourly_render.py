"""HTML for the hourly production TV screen (1920×1080, one screen, no scrolling, read from across the room).

Reading order: the header says where and when; the two hero panels answer "is this shift on pace?" (big shift
number, pace against the target so far, burn-up chart); the KPI matrix gives hour / day / month to date / month
outlook for OB, coal, SR and distance; the fleet boards show who is behind, hour by hour.
Design tokens as the equipment screen: teal = target met, orange = below target, yellow = the current hour.
"""
from __future__ import annotations

import datetime as dt
from html import escape

import pandas as pd

from core import brand
from core import theme as T
from core.config import WIB
from core.hourly import REMARKS, SLOTS, remark_category, remark_tag
from core.hourly_tv import GROUPS, HourlyTv
from core.tv_render import FONT, KIOSK_CSS, _svg

OK, MISS, NOW = T.PA_COLOR, T.MISS, T.ACCENT
UNIT = {"OB": "BCM", "CG": "t"}
TITLE = {"OB": "Overburden", "CG": "Coal"}
# Two palettes: dark for the site TV, light for screenshots shared in chat groups or bright rooms. Fills keep the
# data colours; text colours (…T) are darker in light mode so they stay readable on paper white.
THEMES = ("dark", "light")
PALETTE = {
    "dark": {**T.DARK, "NOW": NOW, "NOWT": NOW, "ONNOW": T.BG, "OK": OK, "MISS": MISS, "OKT": OK, "MISST": MISS,
             "OB": T.ACCENT, "CG": T.READY, "IDLE": T.IDLE, "OKBG": "rgba(79,193,166,.30)",
             "MISSBG": "rgba(240,138,60,.36)", "RDOWN": "#FF6B6B", "RDELAY": "#7FB3E0", "RMAINT": "#C08BE0"},
    "light": {**T.LIGHT, "NOW": NOW, "NOWT": "#8A6A00", "ONNOW": "#141517", "OK": OK, "MISS": MISS,
              "OKT": "#1E7F67", "MISST": "#B4520F", "OB": "#B88A00", "CG": "#2F78B5", "IDLE": "#7FA9CC",
              "OKBG": "rgba(79,193,166,.28)", "MISSBG": "rgba(240,138,60,.30)", "RDOWN": "#C62828",
              "RDELAY": "#2F6EA8", "RMAINT": "#8A3FB0"},
}

CSS_TEMPLATE = """
@font-face{font-family:'IBM Plex Sans';font-weight:400;src:url(/app/static/fonts/ibm-plex-sans-400.woff2) format('woff2')}
@font-face{font-family:'IBM Plex Sans';font-weight:500;src:url(/app/static/fonts/ibm-plex-sans-500.woff2) format('woff2')}
@font-face{font-family:'IBM Plex Sans';font-weight:600;src:url(/app/static/fonts/ibm-plex-sans-600.woff2) format('woff2')}
@font-face{font-family:'IBM Plex Sans';font-weight:700;src:url(/app/static/fonts/ibm-plex-sans-700.woff2) format('woff2')}
.hv{container-type:inline-size;background:%(BG)s;color:%(TEXT)s;font-family:%(F)s;font-variant-numeric:tabular-nums;
 box-sizing:border-box;padding:.9cqw 1.2cqw;display:flex;flex-direction:column;gap:.7cqw;overflow:hidden}
.hv.preview{aspect-ratio:16/9;width:100%%;border-radius:4px}
.hv.kiosk{width:min(100vw,177.78vh);height:min(100vh,56.25vw);margin:0 auto}
.hv *{box-sizing:border-box;font-family:%(F)s;min-width:0}
.hv table,.hv td,.hv th{color:%(TEXT)s}
.hh{display:flex;justify-content:space-between;align-items:center;border-bottom:.08cqw solid %(LINE)s;padding-bottom:.45cqw}
.hh .l{display:flex;align-items:baseline;gap:1cqw}
.hh img{width:1.8cqw;height:1.8cqw;align-self:center}
.hh .site{font-size:1.9cqw;font-weight:700;letter-spacing:-.01em}
.hh .what{font-size:1.1cqw;color:%(MUTED)s}.hh .what b{color:%(TEXT)s;font-weight:600}
.hh .hr{font-size:1.1cqw;font-weight:700;color:%(ONNOW)s;background:%(NOW)s;padding:.05cqw .55cqw;border-radius:.2cqw}
.hh .r{display:flex;align-items:baseline;gap:1.2cqw;font-size:.95cqw;color:%(MUTED)s}
.hh .r b{color:%(TEXT)s;font-weight:600}.hh .app{font-weight:700;letter-spacing:.08em}
.hh .app{display:inline-flex;flex-direction:column;align-items:flex-end;line-height:1.1;vertical-align:middle}.hh .app small{font-size:.62em;font-weight:500;letter-spacing:.02em;opacity:.75}
.hh .clk{font-size:1.8cqw;font-weight:600;color:%(TEXT)s}
.top{display:grid;grid-template-columns:1fr 1fr 1.25fr;gap:1.1cqw;height:17.5cqw}
.hero{display:grid;grid-template-rows:auto minmax(0,1fr);gap:.2cqw;border-top:.2cqw solid var(--c);padding-top:.35cqw}
.hero .t{display:flex;justify-content:space-between;align-items:baseline}
.hero .name{font-size:1.05cqw;font-weight:600;color:%(MUTED)s;letter-spacing:.03em;text-transform:uppercase}
.hero .big{font-size:3.1cqw;font-weight:700;line-height:1;letter-spacing:-.03em}
.hero .big small{font-size:1cqw;font-weight:500;color:%(MUTED)s;margin-left:.3cqw;letter-spacing:0}
.hero .pace{font-size:.95cqw;color:%(MUTED)s;text-align:right;line-height:1.35}
.hero .pace b{font-size:1.25cqw}
.hero .chart{width:100%%;height:100%%;display:block;object-fit:contain;object-position:left bottom}
.kpi{border-collapse:collapse;width:100%%;height:100%%;table-layout:fixed}
.kpi th{font-size:.82cqw;font-weight:600;color:%(MUTED)s;text-align:left;padding:0 .4cqw .3cqw;border-bottom:.08cqw solid %(LINE)s;white-space:nowrap}
.kpi th:first-child{width:14%%}
.kpi td{padding:.25cqw .4cqw;border-bottom:.06cqw solid %(LINE)s;vertical-align:middle}
.kpi td.m{font-size:.9cqw;color:%(MUTED)s;white-space:nowrap}
.kpi .a{font-size:1.25cqw;font-weight:600;line-height:1.05}
.kpi .s{font-size:.72cqw;color:%(MUTED)s;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kpi .s b{font-weight:600}
.bar{height:.22cqw;background:%(LINE)s;margin-top:.15cqw;border-radius:.1cqw;overflow:hidden}
.bar i{display:block;height:100%%}
.brd{display:flex;flex-direction:column}
.brd .bt{display:flex;align-items:baseline;gap:1cqw;margin-bottom:.2cqw}
.brd .bt h3{margin:0;font-size:1cqw;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--c)}
.brd .bt span{font-size:.82cqw;color:%(DIM)s}
.ft{width:100%%;border-collapse:collapse;table-layout:fixed}
.ft th{font-size:.7cqw;color:%(DIM)s;font-weight:500;padding:.1cqw .25cqw;text-align:right;border-bottom:.08cqw solid %(LINE)s;white-space:nowrap}
.ft td{font-size:.8cqw;padding:.12cqw .25cqw;text-align:right;border-bottom:.05cqw solid %(LINE)s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ft .l{text-align:left}.ft td.u{font-weight:600;color:%(TEXT)s}.ft td.mu,.ft td.tg{color:%(MUTED)s}
.ft td.h{font-weight:500}.ft td.hi{background:%(OKBG)s}.ft td.lo{background:%(MISSBG)s}
.ft td.now{box-shadow:inset 0 0 0 .12cqw %(NOW)s}.ft th.now{color:%(NOWT)s;font-weight:700}
.ft td.fu,.ft tr.rf td{color:%(DIM)s}.ft td.tot{font-weight:700}
.ft td.ach{padding-right:.5cqw}.ft td.ach .bar{margin:0;height:.3cqw}
.ev{margin-top:.35cqw;font-size:var(--ef,.88cqw)}
.ev .fl{display:grid;grid-template-columns:5.4cqw minmax(0,1fr);gap:.8cqw;padding:.32cqw 0 .32cqw .55cqw;
 border-left:.3cqw solid var(--c);border-bottom:.05cqw solid %(LINE)s;font-size:1em;line-height:1.5}
.ev .fl .u{font-weight:700}
.ev .it{margin-right:1.3cqw}.ev .it .hd{white-space:nowrap}.ev .it .t{color:%(MUTED)s;font-weight:600;margin-right:.35cqw}
.ev .it b{font-weight:600}.ev .it .n{color:%(MUTED)s}.ev .it .rc{margin-right:.35cqw;font-size:.8em}
.ev .it.on{background:color-mix(in srgb,%(NOW)s 18%%,%(BG)s);border-radius:.2cqw;padding:0 .25cqw}
.ev .it .now{font-size:.68em;font-weight:700;letter-spacing:.06em;color:%(ONNOW)s;background:%(NOW)s;padding:.02cqw .25cqw;
 border-radius:.15cqw;margin-right:.35cqw;vertical-align:.1cqw}
.rc{display:inline-block;font-style:normal;font-weight:700;font-size:.72cqw;line-height:1.15;letter-spacing:.04em;
 color:var(--k);border:.09cqw solid var(--k);background:color-mix(in srgb,var(--k) 22%%,%(BG)s);
 padding:.03cqw .28cqw;border-radius:.6cqw;vertical-align:.06cqw;text-transform:uppercase}
.rc.down,.mk.down{--k:%(RDOWN)s}.rc.delay,.mk.delay{--k:%(RDELAY)s}
.rc.maint,.mk.maint{--k:%(RMAINT)s}.rc.info,.rc.note,.mk.info,.mk.note{--k:%(MUTED)s}
.ft td.mk{box-shadow:inset 0 -.26cqw 0 var(--k)}.ft td.mk.now{box-shadow:inset 0 0 0 .12cqw %(NOW)s,inset 0 -.38cqw 0 var(--k)}
.ft tr.hk td{border-bottom:none}
.ft tr.rk td{text-align:center;padding:0 .1cqw .14cqw;overflow:visible}
.ft tr.rk td.rkl{text-align:right;font-size:.6cqw;color:%(DIM)s;padding-right:.4cqw}
.ft tr.rk .rc sup{font-size:.85em;margin-left:.15cqw;vertical-align:0;letter-spacing:0;opacity:.85}
.ft td.hl{color:%(MUTED)s;font-size:.72cqw;white-space:normal;line-height:1.25;overflow:visible}.ft td.hl b{color:%(TEXT)s;font-weight:600}
.ft td.op{font-weight:600;color:%(TEXT)s;font-size:.76cqw;white-space:normal;line-height:1.2;overflow:visible}
.kpi td.m span{color:%(DIM)s}
.ft tr.tt td{font-weight:700;border-top:.1cqw solid %(MUTED)s;border-bottom:none}
.ft tr.rf td{color:%(DIM)s;border-bottom:none}
.none{font-size:.9cqw;color:%(DIM)s;padding:.3cqw 0}
.fo{margin-top:auto;display:flex;gap:1.6cqw;font-size:.78cqw;color:%(DIM)s;align-items:center}
.fo i{display:inline-block;width:.7cqw;height:.7cqw;margin-right:.3cqw;vertical-align:-.08cqw;border-radius:.1cqw}
.hv.dense .ft td{font-size:.68cqw;padding:.04cqw .25cqw}.hv.dense .ft th{font-size:.62cqw}
.hv.dense .top{height:15.5cqw}.hv.dense .hero .big{font-size:2.6cqw}
"""
CSS = {k: CSS_TEMPLATE % {**p, "F": FONT} for k, p in PALETTE.items()}


def _n(v, d=0) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:,.{d}f}"


def _pct(v) -> str:
    return "—" if v is None or pd.isna(v) else f"{v * 100:.0f}%"


def _tone(ach, p: dict | None = None) -> str:
    p = p or PALETTE["dark"]
    if ach is None or pd.isna(ach):
        return p["MUTED"]
    return p["OKT"] if ach >= 1 else (p["NOWT"] if ach >= .9 else p["MISST"])


def _bar(ach, p: dict | None = None) -> str:
    if ach is None or pd.isna(ach):
        return '<div class="bar"></div>'
    return f'<div class="bar"><i style="width:{min(ach, 1) * 100:.0f}%;background:{_tone(ach, p)}"></i></div>'


# ------------------------------------------------------------------ burn-up chart (SVG image)
def _burnup(g: str, tot: dict, now: int | None, shift: str, p: dict) -> str:
    """Bars = volume per hour (teal met / orange below its target tick); lines = cumulative actual vs cumulative
    target, with the run-rate projection to the end of the shift. The current hour bar pulses (SMIL, no script)."""
    w, h, x0, x1, top, base = 960, 300, 8, 840, 34, 262
    vals, tg = tot["slots"], tot["target_slots"]
    last = now or 12
    step = (x1 - x0) / 12
    vmax = max([*vals, *tg, 1.0]) * 1.12
    y = lambda v: base - (base - top) * v / vmax  # noqa: E731
    cum = pd.Series(vals).cumsum().tolist()
    worked = [v for v in vals[:last] if v > 0]
    rate = sum(worked) / len(worked) if worked else 0.0
    # hours not started yet carry the target of the last worked hour, so the target line reaches shift end
    ref = next((t for t in reversed(tg[:last]) if t), 0.0)
    cum_tg = pd.Series([t if (t or k < last) else ref for k, t in enumerate(tg)]).cumsum().tolist()
    proj_end = cum[last - 1] + rate * (12 - last) if now else cum[-1]
    cmax = max(cum_tg[-1], proj_end, cum[last - 1], 1.0) * 1.08
    yc = lambda v: base - (base - top) * v / cmax  # noqa: E731
    out = [f'<line x1="{x0}" x2="{x1}" y1="{base}" y2="{base}" stroke="{p["LINE"]}" stroke-width="2"/>']
    for k in range(1, 13):
        cx = x0 + step * (k - 0.5)
        bw = step * 0.6
        v, t = vals[k - 1], tg[k - 1]
        bold = ' font-weight="700"' if k == now else ""
        out.append(f'<text x="{cx:.1f}" y="{base + 27}" font-size="17" text-anchor="middle" '
                   f'fill="{p["NOWT"] if k == now else p["DIM"]}"{bold}>{SLOTS[shift][k - 1][:2]}</text>')
        if now and k > now:
            out.append(f'<rect x="{cx - bw / 2:.1f}" y="{base - 5}" width="{bw:.1f}" height="5" fill="{p["LINE"]}"/>')
            continue
        color = (p["OK"] if v >= t else p["MISS"]) if t else p["IDLE"]
        yy = y(v)
        anim = ('<animate attributeName="opacity" values="1;.45;1" dur="2.4s" repeatCount="indefinite"/>'
                if k == now else "")
        out.append(f'<rect x="{cx - bw / 2:.1f}" y="{yy:.1f}" width="{bw:.1f}" height="{base - yy:.1f}" rx="2" '
                   f'fill="{color}" fill-opacity=".85">{anim}</rect>')
        if t:
            out.append(f'<line x1="{cx - bw / 2 - 4:.1f}" x2="{cx + bw / 2 + 4:.1f}" y1="{y(t):.1f}" y2="{y(t):.1f}" '
                       f'stroke="{p["TEXT"]}" stroke-width="2.5" stroke-opacity=".75"/>')
        if v:
            out.append(f'<text x="{cx:.1f}" y="{yy - 8:.1f}" font-size="18" text-anchor="middle" '
                       f'fill="{p["NOWT"] if k == now else p["MUTED"]}">{_n(v)}</text>')
    pts = " ".join(f"{x0 + step * (k - 0.5):.1f},{yc(cum_tg[k - 1]):.1f}" for k in range(1, 13))
    out.append(f'<polyline points="{pts}" fill="none" stroke="{p["TEXT"]}" stroke-width="2" stroke-opacity=".55" '
               f'stroke-dasharray="6 6"/>')
    pts = " ".join(f"{x0 + step * (k - 0.5):.1f},{yc(cum[k - 1]):.1f}" for k in range(1, last + 1))
    out.append(f'<polyline points="{pts}" fill="none" stroke="{p[g]}" stroke-width="4" '
               f'stroke-linejoin="round" stroke-linecap="round"/>')
    ex, ey = x0 + step * (last - 0.5), yc(cum[last - 1])
    out.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="6" fill="{p[g]}"/>')
    if now and now < 12:
        px, py = x0 + step * 11.5, yc(proj_end)
        out.append(f'<line x1="{ex:.1f}" y1="{ey:.1f}" x2="{px:.1f}" y2="{py:.1f}" stroke="{p[g]}" '
                   f'stroke-width="2.5" stroke-dasharray="3 7" stroke-linecap="round"/>')
        out.append(f'<text x="{x1 + 6}" y="{yc(proj_end) - 16:.1f}" font-size="19" font-weight="600" '
                   f'fill="{p[g]}">end {_n(proj_end)}</text>')
    ty = yc(cum_tg[-1])
    out.append(f'<text x="{x1 + 6}" y="{ty + 8:.1f}" font-size="18" fill="{p["MUTED"]}">target</text>')
    out.append(f'<text x="{x1 + 6}" y="{ty + 30:.1f}" font-size="18" fill="{p["MUTED"]}">{_n(cum_tg[-1])}</text>')
    return _svg(w, h, "".join(out))


def _hero(g: str, d: HourlyTv, p: dict) -> str:
    tot = d.totals.get(g) or {}
    if not tot.get("slots"):
        tot = {"slots": [0.0] * 12, "target_slots": [0.0] * 12, "running": [0] * 12, "total": 0.0, "haulers": 0}
    last = d.slot if d.live else 12
    so_far = sum(tot["target_slots"][:last])
    pace = tot["total"] / so_far if so_far else None
    fleets = len(d.fleets.get(g, pd.DataFrame()))
    return (f'<div class="hero" style="--c:{p[g]}"><div class="t"><div>'
            f'<div class="name">{TITLE[g]} · shift {d.shift}</div>'
            f'<div class="big">{_n(tot["total"])}<small>{UNIT[g]}</small></div></div>'
            f'<div class="pace"><b style="color:{_tone(pace, p)}">{_pct(pace)}</b> of target so far<br>'
            f'target {_n(so_far)} · {fleets} fleet{"s" if fleets != 1 else ""} · {tot.get("haulers", 0)} haulers'
            f'</div></div>{_burnup(g, tot, d.slot if d.live else None, d.shift, p)}</div>')


# ------------------------------------------------------------------ KPI matrix
METRICS = [("OB", "OB", "BCM", 0), ("Coal", "Coal", "t", 0), ("SR", "SR", "BCM/t", 1), ("Distance", "Distance", "m", 0)]


def _kpi(d: HourlyTv, p: dict) -> str:
    hour = SLOTS[d.shift][d.slot - 1] if d.slot else "—"
    cols = [("Hour", f"Hour {hour}" if d.live else f"Last hour {hour}"),
            ("Daily", f"Day · {d.date.day} {d.date:%b}"), ("MTD", "Month to date"), ("Outlook", "Month outlook")]
    head = "<tr><th></th>" + "".join(f"<th>{escape(t)}</th>" for _, t in cols) + "</tr>"
    body = ""
    for key, name, unit, dec in METRICS:
        body += f'<tr><td class="m">{name} <span style="font-size:.7cqw">{unit}</span></td>'
        for blk, _ in cols:
            a, t, ach = d.summary.get(blk, {}).get(key, (None, None, None))
            extra = ""
            if blk == "Daily" and key in d.daily_outlook:
                out = d.daily_outlook[key]
                ach = out / t if t else ach
                extra = f'<div class="s">outlook <b>{_n(out, dec)}</b></div>'
            elif blk == "Outlook" and key in d.month_runrate:
                state = "" if a is None else ("still to go · " if a > 0 else "ahead of plan · ")
                extra = f'<div class="s">{state}run rate <b>{_n(d.month_runrate[key], dec)}</b></div>'
                a = abs(a) if a is not None else a
            body += (f'<td><div class="a">{_n(a, dec)}</div><div class="s">target {_n(t, dec)} · '
                     f'<b style="color:{_tone(ach, p)}">{_pct(ach)}</b></div>{extra}{_bar(ach, p)}</td>')
        body += "</tr>"
    return f'<table class="kpi">{head}{body}</table>'


# ------------------------------------------------------------------ fleet boards
def _board(g: str, d: HourlyTv, p: dict) -> str:
    df = d.fleets.get(g, pd.DataFrame())
    tot = d.totals.get(g, {})
    now = d.slot if d.live else None
    labels = SLOTS[d.shift]
    # haulers keep their full width (a wrapped hauler list makes every row taller); operator names wrap instead
    cols = ('<col style="width:1.6%"><col style="width:4.6%"><col style="width:6.4%"><col style="width:4%">'
            '<col style="width:13%"><col style="width:6.4%"><col style="width:8%"><col style="width:3%">'
            + '<col style="width:3.5%">' * 12 + '<col style="width:4.4%"><col>')
    th = ("<tr><th class='l'>#</th><th class='l'>Loader</th><th class='l'>Operator</th><th class='l'>Model</th>"
          "<th class='l'>Haulers</th><th class='l'>Material</th><th class='l'>PIT → disposal</th><th>Target</th>"
          + "".join(f"<th class='{'now' if i == now else ''}'>{lab}</th>" for i, lab in enumerate(labels, 1))
          + "<th>Total</th><th>Ach</th></tr>")
    rows = ""
    for i, r in enumerate(df.itertuples(index=False), 1):
        cells, hours, tags = "", 0, []
        for k in range(1, 13):
            v = getattr(r, f"s{k}")
            if now and k > now:
                cells += "<td class='fu'>·</td>"
                continue
            cls = ["h"]
            if pd.notna(r.target) and r.target:
                if v >= r.target:
                    cls.append("hi")
                elif v > 0 or (now and k < now) or not now:
                    cls.append("lo")
            if k == now:
                cls.append("now")
            first = (getattr(r, f"m{k}", "") or "").split()[:1]
            if first:
                cls += ["mk", remark_category(first[0])]
            hours += 1
            cells += f"<td class='{' '.join(cls)}'>{_n(v)}</td>"
        for k in range(1, 13):
            codes = (getattr(r, f"m{k}", "") or "").split()
            tags.append((f"<i class='rc {remark_category(codes[0])}'>{escape(remark_tag(codes[0]))}"
                         + (f"<sup>+{len(codes) - 1}</sup>" if len(codes) > 1 else "") + "</i>") if codes else "")
        ach = r.total / (r.target * hours) if pd.notna(r.target) and r.target and hours else None
        route = " → ".join(x for x in (r.pit, r.disposal) if isinstance(x, str) and x)
        has_tags = any(tags)
        rows += (f"<tr{' class=hk' if has_tags else ''}><td class='l mu'>{i}</td><td class='l u'>{escape(str(r.loader))}</td>"
                 f"<td class='l op'>{escape(str(r.operator or '—'))}</td>"
                 f"<td class='l mu'>{escape(str(r.model or ''))}</td>"
                 f"<td class='l hl'><b>{r.haulers}</b> · {escape(r.hauler_ids or '')}</td>"
                 f"<td class='l mu'>{escape(str(r.material or ''))}</td>"
                 f"<td class='l mu'>{escape(route)}</td><td class='tg'>{_n(r.target)}{'*' if r.on_default else ''}</td>{cells}"
                 f"<td class='tot'>{_n(r.total)}</td><td class='ach'>{_bar(ach, p)}</td></tr>")
        if has_tags:   # remarks get their own thin row under the trips: a marker must never look like a figure
            rows += ("<tr class='rk'><td class='l rkl' colspan='8'>remarks ↑</td>"
                     + "".join(f"<td>{t}</td>" for t in tags) + "<td></td><td></td></tr>")
    if df.empty:
        rows = (f"<tr><td class='l' colspan='22'><div class='none'>No {TITLE[g].lower()} input for this shift yet."
                "</div></td></tr>")
    else:
        hide = lambda k: bool(now and k > now)  # noqa: E731
        s_cells = "".join("<td></td>" if hide(k) else f"<td>{_n(v)}</td>" for k, v in enumerate(tot["slots"], 1))
        r_cells = "".join("<td></td>" if hide(k) else f"<td>{v}</td>" for k, v in enumerate(tot["running"], 1))
        rows += (f"<tr class='tt'><td class='l' colspan='8'>Total {UNIT[g]}</td>{s_cells}"
                 f"<td class='tot'>{_n(tot['total'])}</td><td></td></tr>"
                 f"<tr class='rf'><td class='l' colspan='8'>Running fleet</td>{r_cells}<td></td><td></td></tr>")
    sub = (f"{UNIT[g]} per hour · {len(df)} fleets · {tot.get('haulers', 0)} haulers · "
           f"{_n(tot.get('trips'))} trips")
    return (f'<div class="brd" style="--c:{p[g]}"><div class="bt"><h3>{TITLE[g]}</h3><span>{sub}</span>'
            f'</div><table class="ft"><colgroup>{cols}</colgroup>{th}{rows}</table>{_events(d, g, p)}</div>')


def _event_item(d: HourlyTv, r) -> str:
    """One remark inline: hour(s), tag, description, truck, note."""
    has = isinstance(r.code, str) and r.code
    sl = SLOTS[d.shift]   # '09-10' for one hour, '09–12' for 09-10 … 11-12
    hrs = sl[r.slot_from - 1] if r.slot_from == r.slot_to else f"{sl[r.slot_from - 1][:2]}–{sl[r.slot_to - 1][-2:]}"
    on = bool(d.live and d.slot and r.slot_from <= d.slot <= r.slot_to)
    tag = remark_tag(r.code if has else None)
    desc = REMARKS.get(str(r.code), str(r.code)) if has else ""
    truck = r.hauler if isinstance(r.hauler, str) and r.hauler else ""
    note = r.remark if isinstance(r.remark, str) and r.remark else ""
    return (f"<span class='it{' on' if on else ''}'><span class='hd'><span class='t'>{hrs}</span>"
            + ("<i class='now'>NOW</i>" if on else "")
            + f"<i class='rc {remark_category(r.code if has else None)}'>{escape(tag)}</i></span>"
            + (f"<b>{escape(desc)}</b>" if desc else "") + (f" · {escape(truck)}" if truck else "")
            + (f" <span class='n'>{'— ' if desc or truck else ''}{escape(note)}</span>" if note else "") + "</span>")


def _events(d: HourlyTv, g: str, p: dict) -> str:
    """Remarks of one board, right under its table: one block per excavator of that board, every remark in full and
    in hour order (the excavator is not repeated per remark, text wraps)."""
    ev = d.events
    df = d.fleets.get(g, pd.DataFrame())
    if ev is None or ev.empty or df.empty:
        return ""
    blocks = ""
    for ld in df["loader"].tolist():
        e = ev[ev["loader"] == ld].sort_values(["slot_from", "slot_to"])
        if e.empty:
            continue
        items = "".join(_event_item(d, r) for r in e.itertuples())
        blocks += (f"<div class='fl' style='--c:{p[g]}'><span class='u'>{escape(str(ld))}</span>"
                   f"<span>{items}</span></div>")
    return f'<div class="ev">{blocks}</div>' if blocks else ""


# When everything does not fit on the screen, the browser shrinks the remark text step by step (down to a readable
# minimum) instead of cutting the legend off. Nothing moves; it is measured again on every redraw.
# Still too tall at the smallest remark size: switch to the dense layout (smaller rows) and fit again.
FIT_SCRIPT = ("<script>(function(){const hv=document.currentScript.parentElement;"
              "const over=()=>hv.scrollHeight>hv.clientHeight+1;"
              "const shrink=()=>{let f=0.88;hv.style.setProperty('--ef',f+'cqw');"
              "while(f>0.56&&over()){f=Math.round((f-0.04)*100)/100;hv.style.setProperty('--ef',f+'cqw')}};"
              "const fit=()=>{shrink();if(over()&&!hv.classList.contains('dense')){hv.classList.add('dense');shrink()}};"
              "(document.fonts?document.fonts.ready:Promise.resolve()).then(()=>requestAnimationFrame(fit))})()</script>")


def render(d: HourlyTv, kiosk: bool = False, now: dt.datetime | None = None, theme: str = "dark") -> str:
    """`theme` 'dark' (site TV) or 'light' (screenshots for chat groups, bright rooms)."""
    theme = theme if theme in PALETTE else "dark"
    p = PALETTE[theme]
    now = (now or dt.datetime.now(dt.UTC)).astimezone(WIB)
    mode = "kiosk" if kiosk else "preview"
    page_bg = (f".stApp,[data-testid='stAppViewContainer'],[data-testid='stMain']{{background:{p['BG']}!important}}"
               if kiosk else "")
    css = f"<style>{CSS[theme]}{KIOSK_CSS if kiosk else ''}{page_bg}</style>"
    hour = SLOTS[d.shift][d.slot - 1] if d.slot else ""
    upd = (f"input <b>{d.updated_at.astimezone(WIB):%H:%M}</b>" + (f" · {escape(d.updated_by)}" if d.updated_by
                                                                     else "")
           if d.updated_at is not None else "no input yet")
    off = (f"official to {d.official_until.day} {d.official_until:%b}, flash after" if d.official_until
           else "flash data")
    head = (f'<div class="hh"><div class="l"><img alt="" src="{brand.data_uri("logo-64.png")}">'
            f'<span class="site">{escape(d.site)}</span>'
            f'<span class="what">Hourly production · <b>{d.date.day} {d.date:%b %Y}</b> · shift <b>{d.shift}</b>'
            f'</span>' + (f'<span class="hr">{hour}</span>' if d.live else "")
            + f'</div><div class="r"><span>Shift boss <b>{escape(d.coordinator or "—")}</b></span><span>{upd}</span>'
              f'<span class="app">{brand.NAME}<small>{escape(brand.FULL_NAME)}</small></span><span class="clk">{now:%H:%M}</span></div></div>')
    top = f'<div class="top">{_hero("OB", d, p)}{_hero("CG", d, p)}{_kpi(d, p)}</div>'
    boards = _board("OB", d, p) + _board("CG", d, p)
    foot = (f'<div class="fo"><span><i style="background:rgba(79,193,166,.6)"></i>target met</span>'
            f'<span><i style="background:rgba(240,138,60,.7)"></i>below target</span>'
            f'<span><i style="box-shadow:inset 0 0 0 .12cqw {NOW}"></i>current hour</span>'
            f'<span>{"white" if theme == "dark" else "dark"} tick = hourly target · dashed = cumulative target · dotted = projection to shift end</span>'
            f'<span>MTD: {off} · SR = OB BCM per coal t · distance trip-weighted</span>'
            + ('<span>* target = Production Data default (no hourly target yet)</span>'
               if any(len(df) and df["on_default"].any() for df in d.fleets.values()) else '')
            + '</div>')
    lines = sum(len(d.fleets.get(g, pd.DataFrame())) for g in GROUPS)
    dense = " dense" if lines > 16 else ""
    return f'{css}<div class="hv {mode}{dense} {theme}">{head}{top}{boards}{foot}{FIT_SCRIPT}</div>'
