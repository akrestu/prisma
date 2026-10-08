"""Hourly dashboard (flash data): the TV screen for any site and shift, plus interactive charts per hour, fleet,
hauler and operator (the base of operator KPIs), the month trend and the raw lines."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import dash
from core import hourly as H
from core import theme as T
from core.config import UNMAPPED, now_wib
from core.ui import excel_download, fmt_num, require, sites_for
from db import repo
from db.engine import session_scope
from pages.tv.screen import show_hourly, theme_picker

UNIT = {"OB": "BCM", "CG": "t"}
COLOR = {"OB": T.ACCENT, "CG": T.READY}
INK = T.INK   # target lines and neutral labels follow light/dark (Streamlit swaps this placeholder)

user = require("hourly")
sites = [x for x in sites_for(user) if x != UNMAPPED]
st.title("Hourly production")
st.caption("Flash production per hour for any site and shift: the TV screen, plus charts per hour, fleet, "
           "hauler and operator.")
if not sites:
    st.info("No site access.")
    st.stop()

p_date, p_shift, p_slot = H.production_hour(now_wib())
a, b, c, d = st.columns([1.3, 1, 1, 1.2])
site = a.selectbox("Site", sites, key="hp_site")
date = b.date_input("Production date", p_date, key="hp_date", max_value=p_date)
shift = c.segmented_control("Shift", list(H.SHIFTS), default=p_shift, key="hp_shift") or p_shift
group = d.segmented_control("Material", ["OB", "CG"], default="OB", key="hp_group",
                            format_func=lambda g: "Overburden" if g == "OB" else "Coal") or "OB"
live = (date, shift) == (p_date, p_shift)
now_slot = p_slot if live else 12
st.caption(("Live: the shift running now. " if live else "")
           + "Flash data entered per hour, not approved; the official month figures come from Production Data.")

with session_scope() as s:
    month = date.replace(day=1)
    rows = repo.hourly_range(s, [site], month, date)
    remarks = repo.hourly_remarks(s, site, date, shift)
cur = rows[(rows["date"] == date) & (rows["shift"] == shift)] if len(rows) else rows
long = H.to_long(cur) if len(cur) else H.to_long(pd.DataFrame())
lg = long[(long["material_group"] == group) & (long["slot"] <= now_slot)] if len(long) else long
unit = UNIT[group]

t_tv, t_pace, t_fleet, t_ops, t_month, t_lines = st.tabs(
    ["TV screen", "Pace", "Fleets", "Haulers & operators", "Month", "Lines"])

with t_tv:
    theme = theme_picker(st, "hp_theme")
    show_hourly(site, kiosk=False, date=None if live else date, shift=None if live else shift, theme=theme)


def no_data():
    st.info(f"No {'overburden' if group == 'OB' else 'coal'} input for {site} {date:%d %b} {shift}.")


# ------------------------------------------------------------------ pace: hourly bars + cumulative lines
with t_pace:
    if lg.empty:
        no_data()
    else:
        labels = H.SLOTS[shift][:now_slot]
        vol = lg.groupby("slot")["volume"].sum().reindex(range(1, now_slot + 1), fill_value=0)
        fleet_hour = lg[lg["rit"] > 0].drop_duplicates(["slot", "loader"])
        tgt = fleet_hour.groupby("slot")["target_per_hour"].sum().reindex(vol.index, fill_value=0)
        running = fleet_hour.groupby("slot")["loader"].nunique().reindex(vol.index, fill_value=0)
        # one stacked segment per loader (Eq ID), so every bar shows which excavators made the hour
        by_loader = lg.pivot_table(index="loader", columns="slot", values="volume", aggfunc="sum", fill_value=0) \
            .reindex(columns=vol.index, fill_value=0)
        order = lg.groupby("loader")["line"].min().sort_values().index
        # loader colours avoid the semantic ones used in this chart: teal = met, orange = below, yellow = accent
        palette = [T.READY, T.FUEL_COLOR, T.IDLE, T.STANDBY, "#A7D38B", "#7FB3E0", "#D9A5E8", "#8C8FD6", "#B5A48C",
                   "#6FA3A8", "#C9B8E8", "#92B87A"]
        tgt_by = lg.groupby("loader")["target_per_hour"].max()
        fig = go.Figure()
        for i, ld in enumerate(order):
            y = by_loader.loc[ld].to_numpy()
            fig.add_bar(x=labels, y=y, name=str(ld), marker_color=palette[i % len(palette)],
                        customdata=[[tgt_by.get(ld) or 0]] * len(y),
                        hovertemplate=f"<b>{ld}</b> · %{{x}}<br>%{{y:,.0f}} {unit} of %{{customdata[0]:,.0f}}"
                                      "<extra></extra>")
        met = [(v >= t) if t else None for v, t in zip(vol, tgt, strict=True)]
        fig.add_scatter(x=labels, y=vol.values, mode="text", showlegend=False, textposition="top center",
                        text=[f"{v:,.0f}" for v in vol.to_numpy()],
                        textfont=dict(color=[T.PA_COLOR if x else (T.MISS if x is False else INK) for x in met]),
                        customdata=list(zip(tgt, running, strict=True)),
                        hovertemplate="%{x} total %{y:,.0f}<br>target %{customdata[0]:,.0f} · "
                                      "%{customdata[1]} loaders working<extra></extra>")
        fig.add_scatter(x=labels, y=tgt.values, name="Hourly target", mode="markers",
                        marker=dict(symbol="line-ew-open", size=26, color=INK, line=dict(width=3)),
                        hovertemplate="target %{y:,.0f}<extra></extra>")
        fig.add_scatter(x=labels, y=vol.cumsum().values, name="Cumulative actual", yaxis="y2",
                        line=dict(color=COLOR[group], width=4), hovertemplate="cumulative %{y:,.0f}<extra></extra>")
        fig.add_scatter(x=labels, y=tgt.cumsum().values, name="Cumulative target", yaxis="y2",
                        line=dict(color=INK, width=2, dash="dash"),
                        hovertemplate="cumulative target %{y:,.0f}<extra></extra>")
        fig.update_layout(title=f"{'Overburden' if group == 'OB' else 'Coal'} per hour by loader · {date:%d %b} {shift}"
                                "  ·  total: teal = target met, orange = below",
                          yaxis=dict(title=f"{unit} per hour", tickformat=","), bargap=.35, barmode="stack",
                          yaxis2=dict(title="cumulative", overlaying="y", side="right", tickformat=",",
                                      showgrid=False), hovermode="x unified")
        dash.plot(fig, 420)
        k = st.columns(4)
        k[0].metric(f"Shift so far ({unit})", fmt_num(vol.sum()))
        k[1].metric("Target so far", fmt_num(tgt.sum()))
        k[2].metric("Pace", f"{vol.sum() / tgt.sum():.0%}" if tgt.sum() else "—")
        k[3].metric("Trips", fmt_num(lg["rit"].sum()))

# ------------------------------------------------------------------ fleets: heatmap + totals vs target
with t_fleet:
    if lg.empty:
        no_data()
    else:
        per = lg.pivot_table(index="loader", columns="slot", values="volume", aggfunc="sum", fill_value=0) \
            .reindex(columns=range(1, now_slot + 1), fill_value=0)
        info = lg.groupby("loader").agg(target=("target_per_hour", "max"), model=("loader_model", "first"),
                                        operator=("operator", lambda x: ", ".join(dict.fromkeys(x.dropna()))),
                                        haulers=("hauler", "nunique"), line=("line", "min")).sort_values("line")
        per = per.reindex(info.index)
        ratio = per.div(info["target"].replace(0, float("nan")), axis=0).astype(float).clip(upper=1.5)
        hover = [[f"{ld} · {info.loc[ld, 'model'] or ''}<br>{info.loc[ld, 'operator'] or 'no operator'}"
                  f"<br>{H.SLOTS[shift][k - 1]}: {per.loc[ld, k]:,.0f} {unit} of {info.loc[ld, 'target'] or 0:,.0f}"
                  f"<br>{info.loc[ld, 'haulers']} haulers" for k in per.columns] for ld in per.index]
        fig = go.Figure(go.Heatmap(
            z=ratio.values, x=H.SLOTS[shift][:now_slot], y=list(per.index),
            text=per.map(lambda v: f"{v:,.0f}").values, texttemplate="%{text}", hovertext=hover, hoverinfo="text",
            zmin=0, zmax=1.5, xgap=2, ygap=2,
            colorscale=[[0, T.MISS], [.6, "#8A5A34"], [.66, T.PA_COLOR], [1, "#2E8C76"]],
            colorbar=dict(title="of target", tickvals=[0, .5, 1, 1.5], ticktext=["0%", "50%", "100%", "150%"])))
        fig.update_layout(title="Volume per fleet per hour (colour = share of the fleet's hourly target)",
                          yaxis=dict(autorange="reversed", type="category"), xaxis=dict(type="category"))
        dash.plot(fig, max(320, 30 * len(per) + 120))
        tot = per.sum(axis=1)
        plan = info["target"].fillna(0) * per.columns.size
        fig = go.Figure()
        fig.add_bar(y=list(tot.index), x=tot.values, orientation="h", name="Actual",
                    marker_color=[T.PA_COLOR if p and v >= p else T.MISS for v, p in zip(tot, plan, strict=True)],
                    hovertemplate="%{y}: %{x:,.0f}<extra></extra>")
        fig.add_scatter(y=list(tot.index), x=plan.values, mode="markers", name="Target for the hours shown",
                        marker=dict(symbol="line-ns-open", size=22, color=INK, line=dict(width=3)),
                        hovertemplate="target %{x:,.0f}<extra></extra>")
        fig.update_layout(title=f"Shift total per fleet ({unit})",
                          yaxis=dict(autorange="reversed", type="category"), xaxis=dict(tickformat=","))
        dash.plot(fig, max(300, 26 * len(tot) + 110))

# ------------------------------------------------------------------ haulers & operators (base of operator KPIs)
with t_ops:
    if lg.empty:
        no_data()
    else:
        # trips per hauler (Eq ID) per hour, grouped by the loader it worked with
        hl = lg.assign(hauler=lg["hauler"].fillna(lg["hauler_model"]).astype(str),
                       loader=lg["loader"].astype(str))
        trips = hl.pivot_table(index=["loader", "hauler"], columns="slot", values="rit", aggfunc="sum",
                               fill_value=0).reindex(columns=range(1, now_slot + 1), fill_value=0)
        first = hl.groupby(["loader", "hauler"]).agg(line=("line", "min"), model=("hauler_model", "first"),
                                                    op=("hauler_operator", "first")).sort_values("line")
        trips = trips.reindex(first.index)
        # colour: trips vs the hauler's own best hour this shift, so a slow or stopped hour stands out
        best = trips.max(axis=1).replace(0, float("nan"))
        ratio = trips.div(best, axis=0).astype(float)
        ylab = [f"{ld} · {hv}" for ld, hv in trips.index]
        hover = [[f"<b>{hv}</b> {first.loc[(ld, hv), 'model'] or ''} → {ld}<br>{first.loc[(ld, hv), 'op'] or ''}"
                  f"<br>{H.SLOTS[shift][k - 1]}: {trips.loc[(ld, hv), k]:.0f} trips" for k in trips.columns]
                 for ld, hv in trips.index]
        fig = go.Figure(go.Heatmap(
            z=ratio.values, x=H.SLOTS[shift][:now_slot], y=ylab,
            text=trips.map(lambda v: f"{v:.0f}" if v else "·").values, texttemplate="%{text}",
            hovertext=hover, hoverinfo="text", zmin=0, zmax=1, xgap=2, ygap=2,
            colorscale=[[0, T.MISS], [.5, "#8A5A34"], [.75, T.PA_COLOR], [1, "#2E8C76"]],
            colorbar=dict(title="of best hour", tickvals=[0, .5, 1], ticktext=["0%", "50%", "100%"])))
        fig.update_layout(title="Trips per hauler per hour (grouped by loader; colour = share of its best hour)",
                          yaxis=dict(autorange="reversed", type="category"), xaxis=dict(type="category"))
        dash.plot(fig, max(320, 24 * len(trips) + 120))
        tot = pd.DataFrame({"Loader": [ld for ld, _ in trips.index], "Hauler": [hv for _, hv in trips.index],
                            "Model": first["model"].to_numpy(), "Operator": first["op"].to_numpy(),
                            "Hours worked": (trips > 0).sum(axis=1).to_numpy(), "Trips": trips.sum(axis=1).to_numpy(),
                            unit: hl.groupby(["loader", "hauler"])["volume"].sum().reindex(trips.index).to_numpy()})
        tot["Trips/hour"] = tot["Trips"] / tot["Hours worked"].replace(0, float("nan"))
        st.dataframe(tot, hide_index=True, width="stretch",
                     column_config={"Trips/hour": st.column_config.NumberColumn(format="%.1f"),
                                    unit: st.column_config.NumberColumn(format="%,.0f")})
        excel_download(tot, f"hourly_haulers_{site}_{date:%Y-%m-%d}_{shift}_{group}.xlsx", key="hp_haulers")
        st.divider()

        worked = lg[lg["rit"] > 0]
        by =(worked.assign(hauler=worked["hauler"].fillna(worked["hauler_model"]))
              .groupby(["hauler_nrp", "hauler_operator", "hauler", "hauler_model", "loader"], dropna=False)
              .agg(trips=("rit", "sum"), volume=("volume", "sum"), hours=("slot", "nunique")).reset_index())
        by["trips_per_hour"] = by["trips"] / by["hours"]
        by["operator"] = by["hauler_operator"].fillna(by["hauler_nrp"]).fillna("— no operator")
        ops = (by.groupby("operator").agg(trips=("trips", "sum"), volume=("volume", "sum"), hours=("hours", "sum"),
                                         haulers=("hauler", lambda x: ", ".join(sorted(set(map(str, x))))),
                                         loaders=("loader", lambda x: ", ".join(sorted(set(map(str, x))))))
               .assign(tph=lambda x: x["trips"] / x["hours"]).sort_values("tph", ascending=False))
        st.caption("Trips per working hour of each hauler operator this shift: the starting point for operator "
                   "KPIs. Operators are identified by NRP from Setup → Operators.")
        fig = go.Figure(go.Bar(
            x=ops.index, y=ops["tph"], marker_color=COLOR[group],
            customdata=ops[["trips", "volume", "hours", "haulers", "loaders"]].values,
            hovertemplate="%{x}<br>%{y:.1f} trips per hour<br>%{customdata[0]:.0f} trips · %{customdata[1]:,.0f} "
                          + unit + "<br>%{customdata[2]} hours · hauler %{customdata[3]}"
                          "<br>loader %{customdata[4]}<extra></extra>"))
        avg = ops["trips"].sum() / ops["hours"].sum() if ops["hours"].sum() else None
        if avg:
            fig.add_hline(y=avg, line_dash="dash", line_color=INK, annotation_text=f"average {avg:.1f}")
        fig.update_layout(title="Trips per working hour by hauler operator", xaxis=dict(type="category"),
                          yaxis=dict(title="trips / hour"))
        dash.plot(fig, 380)
        show = by.sort_values(["operator", "hauler"])[["operator", "hauler_nrp", "hauler", "hauler_model", "loader",
                                                      "hours", "trips", "trips_per_hour", "volume"]]
        show.columns = ["Operator", "NRP", "Hauler", "Model", "Loader", "Hours", "Trips", "Trips/hour", unit]
        st.dataframe(show, hide_index=True, width="stretch",
                     column_config={"Trips/hour": st.column_config.NumberColumn(format="%.1f"),
                                    unit: st.column_config.NumberColumn(format="%,.0f")})
        excel_download(show, f"hourly_operators_{site}_{date:%Y-%m-%d}_{shift}_{group}.xlsx", key="hp_ops")

# ------------------------------------------------------------------ month
with t_month:
    if rows.empty:
        st.info("No hourly input for this site this month yet.")
    else:
        mlong = H.to_long(rows)
        daily = mlong.pivot_table(index="date", columns="material_group", values="volume", aggfunc="sum",
                                  fill_value=0)
        fig = go.Figure()
        if "OB" in daily:
            fig.add_bar(x=daily.index, y=daily["OB"], name="OB (BCM)", marker_color=T.ACCENT,
                        hovertemplate="%{x|%d %b}: %{y:,.0f} BCM<extra></extra>")
        if "CG" in daily:
            fig.add_scatter(x=daily.index, y=daily["CG"], name="Coal (t)", yaxis="y2",
                            line=dict(color=T.READY, width=3), hovertemplate="%{x|%d %b}: %{y:,.0f} t<extra></extra>")
        plan = dash.plan_range([site], month, date)
        if plan["ob_plan"].notna().any():
            fig.add_scatter(x=plan["date"], y=plan["ob_plan"], name="OB plan", line=dict(color=T.IDLE, dash="dash"))
        fig.update_layout(title=f"Flash production per day · {month:%B %Y}", yaxis=dict(title="BCM", tickformat=","),
                          yaxis2=dict(title="t", overlaying="y", side="right", tickformat=",", showgrid=False),
                          hovermode="x unified")
        dash.plot(fig, 380)
        excel_download(mlong.drop(columns=["updated_at"], errors="ignore"), f"hourly_{site}_{month:%Y-%m}.xlsx",
                       label="Download month (one row per line × hour)", key="hp_dl_m")

# ------------------------------------------------------------------ lines
with t_lines:
    if cur.empty:
        st.caption("No input for this shift.")
    else:
        show = cur.rename(columns=dict(zip(H.R, H.SLOTS[shift], strict=True)))
        cols = ["line", "loader", "loader_model", "operator", "hauler", "hauler_model", "hauler_operator", "material",
                "muatan", "disposal", "pit", "distance_m", "dist_v", "target_per_hour", *H.SLOTS[shift]]
        st.dataframe(show[cols], hide_index=True, width="stretch")
        excel_download(show[cols], f"hourly_{site}_{date:%Y-%m-%d}_{shift}.xlsx", key="hp_dl")
    st.markdown("**Remarks per hour**")
    if remarks.empty:
        st.caption("No remarks for this shift.")
    else:
        rv = pd.DataFrame({"Hour": [H.SLOTS[shift][int(k) - 1] for k in remarks["slot"]], "Excavator": remarks["loader"],
                           "Hauler": remarks["hauler"], "Code": remarks["code"].map(H.remark_label),
                           "Remark": remarks["remark"]})
        st.dataframe(rv, hide_index=True, width="stretch")
