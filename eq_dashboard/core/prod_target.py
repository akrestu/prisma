"""Productivity targets per site: the rules shared by Hourly Production and the productivity dashboard. No Streamlit
or database.

One set per site, each value with an internal (WBK) and a client (BAU) side:
- excavator models: BCM/h for OB and mud, t/h for coal; plus overrides for single excavators;
- hauler models: BCM/h for OB, t/h for coal.
The internal target counts first; the client target is used only where the internal one is empty.

Model names are matched by prefix after dropping 'CAT': a target for '390FL' covers CAT390FL, 'SK520' covers
SK520XDLC-10, '777E' covers 777E-KDP (the longest matching key wins).
"""
from __future__ import annotations

import pandas as pd

BASIS = {"WBK": "internal", "BAU": "client"}
BASIS_LABEL = {"internal": "Internal target (WBK)", "client": "Client target (BAU)"}
BASES = tuple(BASIS_LABEL)
PRIORITY = ("internal", "client")       # internal first; client only where internal is empty
# where an excavator's target came from
UNIT, HOURLY = "unit", "hourly"
SOURCE_LABEL = {UNIT: "unit override", HOURLY: "model target"}


def _str(v) -> str:
    """Text of a cell; '' for None / NaN / pd.NA (an empty grid cell)."""
    return "" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v)


def norm(model) -> str:
    s = _str(model).strip().upper().replace(" ", "")
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
    s = _str(material).upper()
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


def model_target(loader_model, material, targets: pd.DataFrame | None, basis: str) -> float | None:
    """Target of an excavator model for a material (columns ob, mud, coal): mud for mud and mud blending, coal for
    coal; an empty mud or coal value falls back to the OB value."""
    r = _row(targets, loader_model, basis)
    if r is None:
        return None
    cls = material_class(material)
    v = _positive(r["mud"]) if cls in ("MUD", "MUDB") else _positive(r["coal"]) if cls == "CG" else None
    return v or _positive(r["ob"])


def hauler_target(hauler_model, group: str, targets: pd.DataFrame | None, basis: str) -> float | None:
    """Target of a hauler model (columns ob, coal): BCM/h for OB, t/h for coal."""
    r = _row(targets, hauler_model, basis)
    return None if r is None else _positive(r["coal" if group == "CG" else "ob"])


def first_target(fn, *args) -> float | None:
    """`fn(*args, basis)` for the internal basis, else for the client basis (the PRIORITY)."""
    for basis in PRIORITY:
        v = fn(*args, basis)
        if v:
            return v
    return None


def _override(unit, group: str, overrides: pd.DataFrame | None, basis: str) -> float | None:
    if overrides is None or overrides.empty:
        return None
    o = overrides[overrides["basis"] == basis] if "basis" in overrides else overrides
    hit = o[(o["unit_id"] == unit) & (o["material_group"] == group)]
    return _positive(hit["target_per_hour"].iloc[0]) if len(hit) else None


def hourly_target(unit, model, material, overrides: pd.DataFrame | None,
                  models: pd.DataFrame | None) -> tuple[float | None, str | None]:
    """Target per hour of one excavator and its source: the unit override, else the site's target for the model,
    else none. At each step the internal value counts first, the client value only where the internal one is
    empty."""
    group = "CG" if material_class(material) == "CG" else "OB"
    for source, v in ((UNIT, first_target(_override, unit, group, overrides)),
                      (HOURLY, first_target(model_target, model, material, models))):
        if v:
            return v, source
    return None, None


def wide(table: pd.DataFrame, values: dict[str, str]) -> pd.DataFrame:
    """Long (model, basis, value columns) → one row per model with '<label> · <basis>' columns, for editing."""
    cols = [f"{lbl} · {b}" for b in BASES for lbl in values.values()]
    if table is None or table.empty:
        return numeric(pd.DataFrame(columns=["model", *cols]))
    out = table.pivot_table(index="model", columns="basis", values=list(values), aggfunc="first")
    out.columns = [f"{values[v]} · {b}" for v, b in out.columns]
    return numeric(out.reindex(columns=cols).reset_index().sort_values("model").reset_index(drop=True))


def numeric(grid: pd.DataFrame) -> pd.DataFrame:
    """Every column but `model` as float, so empty cells show blank in a grid instead of 'None'."""
    for c in grid.columns:
        if c != "model":
            grid[c] = pd.to_numeric(grid[c], errors="coerce").astype(float)
    return grid


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
