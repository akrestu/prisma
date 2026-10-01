"""Productivity targets: the rules shared by Production Data and Hourly Production. No Streamlit or database.

Two separate sets, each with an internal (WBK) and a client (BAU) value:
- Production Data default, company-wide per equipment model: excavators (OB, mud BCM/h; coal t/h) and haulers
  (OB BCM/h, coal t/h). It changes rarely and is the yardstick of the productivity dashboard.
- Hourly Production target, per site: per excavator model, plus overrides for single units. Where a site has no
  hourly target for an excavator, the Production Data default is used and marked 'default'.

Model names are matched by prefix after dropping 'CAT': a target for '390FL' covers CAT390FL, 'SK520' covers
SK520XDLC-10, '777E' covers 777E-KDP (the longest matching key wins).
"""
from __future__ import annotations

import pandas as pd

BASIS = {"WBK": "internal", "BAU": "client"}
BASIS_LABEL = {"internal": "Internal target (WBK)", "client": "Client target (BAU)"}
BASES = tuple(BASIS_LABEL)
# where an Hourly Production target came from
UNIT, HOURLY, DEFAULT = "unit", "hourly", "default"
SOURCE_LABEL = {UNIT: "unit override", HOURLY: "hourly target", DEFAULT: "Production Data default"}


def norm(model) -> str:
    s = str(model or "").strip().upper().replace(" ", "")
    return s[3:] if s.startswith("CAT") else s


def match(model, keys) -> str | None:
    """The key the population model starts with (longest wins): '6020B' → 'CAT6020B', 'SK480LC-8' → 'SK480'."""
    m = norm(model)
    if not m:
        return None
    hits = [k for k in keys if isinstance(k, str) and norm(k) and m.startswith(norm(k))]
    return max(hits, key=lambda k: len(norm(k))) if hits else None


def material_class(material) -> str:
    """OB | MUDB (mud blending) | MUD | CG, from the material name ('OB - Mud Blending', 'OB - MUD', 'CG - …')."""
    s = str(material or "").upper()
    if s.startswith("CG"):
        return "CG"
    if "MUD" in s and ("BLEND" in s or "BLAND" in s):
        return "MUDB"
    if "MUD" in s:
        return "MUD"
    return "OB"


def _positive(v) -> float | None:
    return float(v) if v is not None and pd.notna(v) and v > 0 else None


def _row(table: pd.DataFrame | None, model, basis: str) -> pd.Series | None:
    if table is None or table.empty or not isinstance(model, str):
        return None
    t = table[table["basis"] == basis]
    key = match(model, t["model"])
    return None if key is None else t[t["model"] == key].iloc[0]


def model_target(loader_model, material, targets: pd.DataFrame, basis: str) -> float | None:
    """Production Data default of an excavator for a material: mud value for mud and mud blending, coal value for
    coal (the OB value when no coal value is set), OB value otherwise."""
    r = _row(targets, loader_model, basis)
    if r is None:
        return None
    cls = material_class(material)
    if cls in ("MUD", "MUDB"):
        return _positive(r["pdty_mud"])
    if cls == "CG":
        return _positive(r.get("pdty_coal")) or _positive(r["pdty_ob"])
    return _positive(r["pdty_ob"])


def hauler_target(hauler_model, group: str, targets: pd.DataFrame, basis: str) -> float | None:
    """Production Data default of a hauler model: BCM/h for OB, t/h for coal."""
    r = _row(targets, hauler_model, basis)
    return None if r is None else _positive(r["pdty_coal" if group == "CG" else "pdty_ob"])


def hourly_target(unit, model, material, basis: str, overrides: pd.DataFrame | None,
                  hourly_models: pd.DataFrame | None, defaults: pd.DataFrame | None) -> tuple[float | None, str | None]:
    """Hourly Production target of one excavator and its source: the unit override, else the site's hourly target
    for the model, else the Production Data default (marked 'default'), else none."""
    group = "CG" if material_class(material) == "CG" else "OB"
    if overrides is not None and len(overrides):
        o = overrides
        if "basis" in o:
            o = o[o["basis"] == basis]
        hit = o[(o["unit_id"] == unit) & (o["material_group"] == group)]
        if len(hit) and _positive(hit["target_per_hour"].iloc[0]):
            return float(hit["target_per_hour"].iloc[0]), UNIT
    r = _row(hourly_models, model, basis)
    if r is not None:
        cls = material_class(material)
        v = _positive(r["mud"]) if cls in ("MUD", "MUDB") else _positive(r["coal"]) if cls == "CG" else None
        v = v or _positive(r["ob"])
        if v:
            return v, HOURLY
    v = model_target(model, material, defaults, basis)
    return (v, DEFAULT) if v else (None, None)


def wide(table: pd.DataFrame, values: dict[str, str]) -> pd.DataFrame:
    """Long (model, basis, value columns) → one row per model with '<label> · <basis>' columns, for editing."""
    cols = [f"{lbl} · {b}" for b in BASES for lbl in values.values()]
    if table is None or table.empty:
        return pd.DataFrame(columns=["model", *cols])
    out = table.pivot_table(index="model", columns="basis", values=list(values), aggfunc="first")
    out.columns = [f"{values[v]} · {b}" for v, b in out.columns]
    return out.reindex(columns=cols).reset_index().sort_values("model").reset_index(drop=True)


def long(grid: pd.DataFrame, values: dict[str, str]) -> pd.DataFrame:
    """Inverse of `wide`: rows without a model or without any value are dropped."""
    recs = []
    for r in grid.to_dict("records"):
        model = str(r.get("model") or "").strip()
        if not model or model.lower() == "nan":
            continue
        for b in BASES:
            vals = {v: _positive(r.get(f"{lbl} · {b}")) for v, lbl in values.items()}
            if any(x is not None for x in vals.values()):
                recs.append({"model": model, "basis": b, **vals})
    out = pd.DataFrame(recs, columns=["model", "basis", *values])
    return out.drop_duplicates(["model", "basis"], keep="last").reset_index(drop=True)
