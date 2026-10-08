"""PIT and disposal master of a site, per material (OB | CG): the drop-down lists of the Hourly Production lines.
A line with trips must use an active PIT and an active disposal of its material. No Streamlit or database here."""
from __future__ import annotations

import pandas as pd

from core.io import text

GROUPS = ("OB", "CG")
KINDS = ("PIT", "DISPOSAL")
KIND_LABEL = {"PIT": "PIT", "DISPOSAL": "Disposal"}
COLS = ["kind", "name", "material_group", "active"]


def _yes(v) -> bool:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return True                                   # empty = active
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() not in ("no", "n", "false", "0", "tidak", "inactive")


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """kind (PIT | DISPOSAL), name, material_group (OB | CG), active → cleaned rows + problems (blocking)."""
    d = df.reindex(columns=COLS).copy()
    d["name"] = text(d["name"].astype("string"))
    d = d[d["name"].notna()].copy()
    d["kind"] = d["kind"].astype("string").str.strip().str.upper().replace({"DISP": "DISPOSAL"})
    d["material_group"] = d["material_group"].astype("string").str.strip().str.upper().str[:2]
    d["active"] = d["active"].map(_yes).astype(bool)
    problems = [f"{n}: type must be PIT or Disposal." for n in d.loc[~d["kind"].isin(KINDS), "name"]]
    problems += [f"{n}: material must be OB or CG." for n in d.loc[~d["material_group"].isin(GROUPS), "name"]]
    key = d["kind"].fillna("") + "|" + d["material_group"].fillna("") + "|" + d["name"].str.upper()
    dup = d[key.duplicated(keep=False)]
    if len(dup):
        problems.append(f"Listed twice (same type and material): {', '.join(sorted(set(dup['name'])))}.")
    too_long = d[d["name"].str.len() > 120]
    if len(too_long):
        problems.append(f"Name longer than 120 characters: {', '.join(too_long['name'].str[:30])}…")
    return d.reset_index(drop=True), problems


def names(locations: pd.DataFrame | None, kind: str, active_only: bool = True) -> list[str]:
    """Sorted names of one kind (both materials), for a drop-down."""
    if locations is None or locations.empty:
        return []
    d = locations[locations["kind"] == kind]
    if active_only:
        d = d[d["active"].astype(bool)]
    return sorted(dict.fromkeys(d["name"]))
