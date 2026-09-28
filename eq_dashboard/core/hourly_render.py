"""HTML for the hourly production TV screen (1920×1080, one screen, no scrolling). Same design tokens as the
equipment screen: orange means below target, teal means target met, yellow frames the current hour."""
from __future__ import annotations

import datetime as dt
from html import escape

import pandas as pd

from core import brand
from core import theme as T
from core.config import WIB
from core.hourly import SLOTS
from core.hourly_tv import GROUPS, HourlyTv
from core.tv_render import FONT, KIOSK_CSS

OK = T.PA_COLOR
METRICS = [("OB", "BCM", 0), ("Coal", "t", 0), ("SR", "", 1), ("Distance", "m", 0)]

CSS = """
@font-face{font-family:'IBM Plex Sans';font-weight:400;src:url(/app/static/fonts/ibm-plex-sans-400.woff2) format('woff2')}
@font-face{font-family:'IBM Plex Sans';font-weight:600;src:url(/app/static/fonts/ibm-plex-sans-600.woff2) format('woff2')}
@font-face{font-family:'IBM Plex Sans';font-weight:700;src:url(/app/static/fonts/ibm-plex-sans-700.woff2) format('woff2')}
.hv{container-type:inline-size;background:%(BG)s;color:%(TEXT)s;font-family:%(F)s;font-variant-numeric:tabular-nums;
 box-sizing:border-box;padding:1cqw 1.3cqw;display:flex;flex-direction:column;gap:.75cqw;overflow:hidden}
.hv.preview{aspect-ratio:16/9;width:100%%;border-radius:4px}
.hv.kiosk{width:min(100vw,177.78vh);height:min(100vh,56.25vw);margin:0 auto}
.hv *{box-sizing:border-box;font-family:%(F)s;min-width:0}
.hh{display:flex;justify-content:space-between;align-items:baseline;border-bottom:.1cqw solid %(LINE)s;padding-bottom:.45cqw}
.hh .site{font-size:2cqw;font-weight:700}.hh .t{font-size:1.15cqw;color:%(ACCENT)s;font-weight:600;margin-left:1cqw}
.hh .s{font-size:1cqw;color:%(MUTED)s;margin-left:1cqw}.hh .clk{font-size:1.8cqw;font-weight:600}
.hh img{width:1.9cqw;height:1.9cqw;margin-right:.7cqw;vertical-align:-.3cqw}
.hh .app{font-size:.95cqw;font-weight:700;letter-spacing:.08em;color:%(MUTED)s;margin-right:1cqw}
.sum{display:grid;grid-template-columns:1fr 1fr 1fr 1.25fr .8fr;gap:.9cqw}
.blk{border:.08cqw solid %(LINE)s;border-radius:.3cqw;padding:.45cqw .6cqw;background:%(SURF)s}
.blk h4{margin:0 0 .25cqw;font-size:1cqw;font-weight:600;color:%(MUTED)s;letter-spacing:.02em}
.blk table{width:100%%;border-collapse:collapse}
.blk th{font-size:.78cqw;color:%(DIM)s;font-weight:400;text-align:right;padding:0 0 .15cqw .3cqw}
.blk th:first-child,.blk td:first-child{text-align:left;padding-left:0}
.blk td{color:%(TEXT)s;font-size:.95cqw;text-align:right;padding:.12cqw 0 .12cqw .3cqw;white-space:nowrap}
.blk td.a{font-weight:600;font-size:1.05cqw}
.dot{display:inline-block;width:.55cqw;height:.55cqw;border-radius:50%%;margin-left:.3cqw;vertical-align:.05cqw}
.coord{font-size:.95cqw;line-height:1.5}.coord b{display:block;font-size:1.05cqw}
.tbl{flex:none;display:flex;flex-direction:column}
.tbl h3{margin:0 0 .3cqw;font-size:1.05cqw;font-weight:700;color:%(ACCENT)s;letter-spacing:.04em}
.ft{width:100%%;border-collapse:collapse;table-layout:fixed}
.ft th{font-size:.72cqw;color:%(DIM)s;font-weight:400;padding:.12cqw .2cqw;text-align:right;border-bottom:.08cqw solid %(LINE)s;white-space:nowrap}
.ft td{color:%(TEXT)s;font-size:.8cqw;padding:.1cqw .2cqw;text-align:right;border-bottom:.06cqw solid %(LINE)s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ft .l{text-align:left}.ft td.u{font-weight:600;color:%(TEXT)s}.ft td.tg{color:%(ACCENT)s;font-weight:600}
.ft td.lo{background:%(MISSBG)s;color:%(TEXT)s}.ft td.hi{background:%(OKBG)s;color:%(TEXT)s}
.ft td.now{outline:.12cqw solid %(ACCENT)s;outline-offset:-.12cqw}
.ft td.tot{font-weight:700}.ft td.rm{text-align:left;color:%(MUTED)s}
.ft tr.tt td{font-weight:700;border-top:.1cqw solid %(MUTED)s;color:%(TEXT)s}.ft tr.run td{color:%(MUTED)s}
.ft th.now{color:%(ACCENT)s;font-weight:700}
.leg{font-size:.8cqw;color:%(DIM)s;display:flex;gap:1.4cqw}
.leg i{display:inline-block;width:.7cqw;height:.7cqw;margin-right:.3cqw;vertical-align:-.05cqw}
.none{font-size:.95cqw;color:%(DIM)s;padding:.4cqw 0}
.hv.dense .ft td{font-size:.68cqw;padding:.05cqw .2cqw}.hv.dense .ft th{font-size:.64cqw;padding:.05cqw .2cqw}
.hv.dense .sum .blk td{font-size:.85cqw;padding:.05cqw 0 .05cqw .3cqw}.hv.dense .tbl h3{font-size:.9cqw;margin:0 0 .15cqw}
""" % {"BG": T.BG, "TEXT": T.TEXT, "MUTED": T.MUTED, "DIM": T.DIM, "LINE": T.LINE, "ACCENT": T.ACCENT,
       "SURF": T.SURFACE, "F": FONT, "MISSBG": "rgba(240,138,60,.55)", "OKBG": "rgba(79,193,166,.45)"}


def _n(v, d=0) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:,.{d}f}"


def _dot(ach) -> str:
    if ach is None or pd.isna(ach):
        return ""
    color = OK if ach >= 1 else (T.ACCENT if ach >= .9 else T.MISS)
    return f'<i class="dot" style="background:{color}"></i>'


def _block(title: str, data: dict, outlook: dict | None = None) -> str:
    head = "<tr><th></th><th>Actual</th>" + ("<th>Outlook</th>" if outlook else "") + "<th>Target</th><th>Ach</th></tr>"
    body = ""
    for name, unit, d in METRICS:
        a, t, ach = data.get(name, (None, None, None))
        if outlook and name in outlook and t:
            ach = outlook[name] / t
        out = f"<td>{_n(outlook.get(name), d)}</td>" if outlook else ""
        body += (f"<tr><td>{name}{f' <small>{unit}</small>' if unit else ''}</td><td class='a'>{_n(a, d)}</td>{out}"
                 f"<td>{_n(t, d)}</td><td>{'—' if ach is None else f'{ach * 100:.1f}%'}{_dot(ach)}</td></tr>")
    return f'<div class="blk"><h4>{escape(title)}</h4><table>{head}{body}</table></div>'


def _fleet(g: str, df: pd.DataFrame, tot: dict, d: HourlyTv) -> str:
    unit = "BCM" if g == "OB" else "t"
    labels = SLOTS[d.shift]
    now = d.slot if d.live else None
    cols = ('<col style="width:2.2%"><col style="width:5.2%"><col style="width:5%"><col style="width:7.5%">'
            '<col style="width:7%"><col style="width:7.5%"><col style="width:3.8%">' + '<col style="width:3.9%">' * 12
            + '<col style="width:4.6%"><col>')
    th = ("<tr><th class='l'>#</th><th class='l'>Unit</th><th class='l'>Model</th><th class='l'>Material</th>"
          "<th class='l'>PIT</th><th class='l'>Disposal</th><th>Target</th>"
          + "".join(f"<th class='{'now' if i == now else ''}'>{lab}</th>" for i, lab in enumerate(labels, 1))
          + "<th>Total</th><th class='l'>Remark</th></tr>")
    rows = ""
    for i, r in enumerate(df.itertuples(index=False), 1):
        cells = ""
        for k in range(1, 13):
            v = getattr(r, f"s{k}")
            cls = []
            if now and k > now:
                cells += "<td style='color:#6E6C66'>·</td>"
                continue
            if pd.notna(r.target) and r.target:
                cls.append("hi" if v >= r.target else ("lo" if v > 0 or (now and k < now) else ""))
            if k == now:
                cls.append("now")
            cells += f"<td class='{' '.join(cls)}'>{_n(v)}</td>"
        rows += (f"<tr><td class='l'>{i}</td><td class='l u'>{escape(str(r.loader))}</td>"
                 f"<td class='l'>{escape(str(r.model or ''))}</td><td class='l'>{escape(str(r.material or ''))}</td>"
                 f"<td class='l'>{escape(str(r.pit or ''))}</td><td class='l'>{escape(str(r.disposal or ''))}</td>"
                 f"<td class='tg'>{_n(r.target)}</td>{cells}<td class='tot'>{_n(r.total)}</td>"
                 f"<td class='rm'>{escape(r.remark or '')}</td></tr>")
    if df.empty:
        rows = f"<tr><td class='l' colspan='21'><div class='none'>No {GROUPS[g].lower()} input for this shift.</div></td></tr>"
    else:
        s_cells = "".join(f"<td>{_n(v)}</td>" if not (now and k > now) else "<td></td>"
                          for k, v in enumerate(tot["slots"], 1))
        r_cells = "".join(f"<td>{v}</td>" if not (now and k > now) else "<td></td>"
                          for k, v in enumerate(tot["running"], 1))
        rows += (f"<tr class='tt'><td class='l' colspan='7'>Total ({unit})</td>{s_cells}"
                 f"<td class='tot'>{_n(tot['total'])}</td><td></td></tr>"
                 f"<tr class='run'><td class='l' colspan='7'>Running fleet</td>{r_cells}<td></td><td></td></tr>")
    return f'<div class="tbl"><h3>{GROUPS[g].upper()}</h3><table class="ft"><colgroup>{cols}</colgroup>{th}{rows}</table></div>'


def render(d: HourlyTv, kiosk: bool = False, now: dt.datetime | None = None) -> str:
    now = (now or dt.datetime.now(dt.UTC)).astimezone(WIB)
    mode = "kiosk" if kiosk else "preview"
    css = f"<style>{CSS}{KIOSK_CSS if kiosk else ''}</style>"
    hour = SLOTS[d.shift][d.slot - 1] if d.slot else "—"
    upd = (f"input {d.updated_at.astimezone(WIB):%H:%M}" + (f" by {escape(d.updated_by)}" if d.updated_by else "")
           if d.updated_at is not None else "no input yet")
    head = (f'<div class="hh"><div><img alt="" src="{brand.data_uri("logo-64.png")}"><span class="site">'
            f'{escape(d.site)}</span><span class="t">Hourly production · {d.date.day} {d.date:%b %Y} · {d.shift}'
            f'{" · " + hour if d.live else ""}</span><span class="s">flash data · {upd}</span></div>'
            f'<div><span class="app">{brand.NAME}</span><span class="clk">{now:%H:%M}</span></div></div>')
    off = (f"official data to {d.official_until.day} {d.official_until:%b}, flash after"
           if d.official_until else "flash data")
    summary = ('<div class="sum">'
               + _block(f"Hour {hour}" if d.live else f"Last hour {hour}", d.summary.get("Hour", {}))
               + _block("Month to date", d.summary.get("MTD", {}))
               + _block("Outlook month end", d.summary.get("Outlook", {}))
               + _block(f"Daily · {d.date.day} {d.date:%b}", d.summary.get("Daily", {}), d.daily_outlook)
               + f'<div class="blk coord"><h4>Coordinator</h4><b>{escape(d.coordinator or "—")}</b>'
                 f'<span style="color:{T.DIM}">{off}</span></div></div>')
    legend = (f'<div class="leg"><span><i style="background:rgba(79,193,166,.6)"></i>target met</span>'
              f'<span><i style="background:rgba(240,138,60,.7)"></i>below target</span>'
              f'<span><i style="outline:.12cqw solid {T.ACCENT}"></i>current hour</span>'
              f'<span>SR = OB BCM per coal t · Distance = trip-weighted haul (m)</span></div>')
    tables = "".join(_fleet(g, d.fleets.get(g, pd.DataFrame()), d.totals.get(g, {}), d) for g in GROUPS)
    lines = sum(len(d.fleets.get(g, pd.DataFrame())) for g in GROUPS)
    dense = " dense" if lines > 18 else ""     # many fleets: smaller rows so everything still fits one screen
    return f'{css}<div class="hv {mode}{dense}">{head}{summary}{tables}{legend}</div>'
