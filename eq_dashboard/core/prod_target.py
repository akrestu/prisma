"""Prod_Target workbook (sheet PDTY): excavator productivity per model and hauler truck factors per model family.

- Excavator block: EqBrand (model), TargetBy (WBK = internal target, BAU = client target), Pdty OB, Pdty Mud (BCM/h).
- Hauler block: EqBrand (model family), truck factor for OB, Mud Blending, Mud and Coal, speeds empty/loaded/average.

Names are matched to the unit population by prefix after dropping 'CAT': '390FL' → CAT390FL, 'SK520XDLC-10' → SK520,
'777E-KDP' → CAT777E, 'CWE37064R' → CWE370. Prod_Target is the master; the Mst Hourly Link Muatan only fills gaps.
No Streamlit or database here.
"""
from __future__ import annotations

import pandas as pd

from core.io import read_workbook
from core.validate import StructureError

BASIS = {"WBK": "internal", "BAU": "client"}
BASIS_LABEL = {"internal": "Internal target (WBK)", "client": "Client target (BAU)"}
DEFAULT_MATERIALS = ("OB - FreeDig", "OB - Ripping", "OB - Blasting", "OB - Top Soil", "OB - MUD",
                     "OB - Mud Blending", "CG - Coal Getting")


def norm(model) -> str:
    s = str(model or "").strip().upper().replace(" ", "")
    return s[3:] if s.startswith("CAT") else s


def match(model, keys) -> str | None:
    """The key the population model starts with (longest wins): '6020B' → 'CAT6020B', 'SK480LC-8' → 'SK480'."""
    m = norm(model)
    if not m:
        return None
    hits = [k for k in keys if m.startswith(norm(k)) and norm(k)]
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


def parse(data: bytes) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(excavator targets [model, basis, pdty_ob, pdty_mud], hauler factors [family, tf_ob, tf_mudb, tf_mud,
    tf_coal, sp_empty, sp_loaded, sp_avg])."""
    raw = read_workbook(data)
    if "PDTY" not in raw:
        raise StructureError(["Sheet 'PDTY' was not found in the Prod_Target workbook."])
    x = raw["PDTY"]
    head = None
    for i in range(min(10, len(x))):
        row = [str(v).strip() for v in x.iloc[i].tolist()]
        if "TargetBy" in row and "Pdty OB" in row:
            head = i
            break
    if head is None:
        raise StructureError(["'PDTY': the header row with 'EqBrand', 'TargetBy', 'Pdty OB' was not found."])
    names = [str(v).strip() for v in x.iloc[head].tolist()]
    col = {n: j for j, n in enumerate(names) if n and n != "nan"}
    ex_brand = names.index("EqBrand")
    hl_brand = names.index("EqBrand", ex_brand + 1) if names.count("EqBrand") > 1 else None
    body = x.iloc[head + 1:]
    num = lambda s: pd.to_numeric(s, errors="coerce")  # noqa: E731
    ex = pd.DataFrame({"model": body.iloc[:, ex_brand].astype("string").str.strip(),
                       "basis": body.iloc[:, col["TargetBy"]].astype("string").str.strip().str.upper().map(BASIS),
                       "pdty_ob": num(body.iloc[:, col["Pdty OB"]]),
                       "pdty_mud": num(body.iloc[:, col["Pdty Mud"]]) if "Pdty Mud" in col else None})
    ex = ex.dropna(subset=["model", "basis"]).drop_duplicates(["model", "basis"], keep="last").reset_index(drop=True)
    hl = pd.DataFrame(columns=["family", "tf_ob", "tf_mudb", "tf_mud", "tf_coal", "sp_empty", "sp_loaded", "sp_avg"])
    if hl_brand is not None:
        pick = {"tf_ob": "TF - OB (BCM)", "tf_mudb": "TF - Mud B. (BCM)", "tf_mud": "TF - Mud (BCM)",
                "tf_coal": "TF - Coal (ton)", "sp_empty": "Sp - Empty (km/h)", "sp_loaded": "Sp - Loaded (km/h)",
                "sp_avg": "Sp - Average (km/h)"}
        hl = pd.DataFrame({"family": body.iloc[:, hl_brand].astype("string").str.strip(),
                           **{k: num(body.iloc[:, col[v]]) if v in col else None for k, v in pick.items()}})
        hl = hl.dropna(subset=["family"]).drop_duplicates("family", keep="last").reset_index(drop=True)
    if ex.empty:
        raise StructureError(["'PDTY': no excavator rows with TargetBy WBK or BAU."])
    return ex, hl


def load_factors(hl: pd.DataFrame, pop_models, materials, fallback: pd.DataFrame | None = None
                 ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load per trip for every truck model of the population × material. Prod_Target families first; models it
    does not cover take the Mst Hourly Link Muatan values of the same model (via hourly.load_model), if any.
    Returns (rows [material, material_group, hauler_model, muatan], report [model, source, detail])."""
    from core.clean import material_group
    from core.hourly import load_model
    tf_col = {"OB": "tf_ob", "MUDB": "tf_mudb", "MUD": "tf_mud", "CG": "tf_coal"}
    fb = fallback if fallback is not None else pd.DataFrame(columns=["material", "hauler_model", "muatan"])
    fb_models = sorted(set(fb["hauler_model"])) if len(fb) else []
    rows, report = [], []
    for pm in sorted({str(x) for x in pop_models if isinstance(x, str) and x.strip()}):
        fam = match(pm, hl["family"]) if len(hl) else None
        if fam is not None:
            f = hl.set_index("family").loc[fam]
            n = 0
            for mat in materials:
                v = f[tf_col[material_class(mat)]]
                if pd.notna(v) and v > 0:
                    rows.append((mat, pm, float(v)))
                    n += 1
            report.append((pm, "Prod_Target", f"family {fam} · {n} materials"))
            continue
        src = load_model(pm, fb_models)
        if src is not None:
            sub = fb[(fb["hauler_model"] == src) & fb["material"].isin(materials)]
            rows += [(r.material, pm, float(r.muatan)) for r in sub.itertuples()]
            report.append((pm, "Mst Hourly", f"Link Muatan model {src} · {len(sub)} materials"))
            continue
        report.append((pm, "—", "not in Prod_Target or Mst Hourly: fill in by hand"))
    out = pd.DataFrame(rows, columns=["material", "hauler_model", "muatan"])
    out.insert(1, "material_group", material_group(out["material"]).to_numpy())
    return out, pd.DataFrame(report, columns=["model", "source", "detail"])


def model_target(loader_model, material, targets: pd.DataFrame, basis: str) -> float | None:
    """Default hourly target of an excavator from its model: Pdty Mud for mud materials, Pdty OB otherwise.
    Coal has no model target (set per unit)."""
    cls = material_class(material)
    if cls == "CG" or targets is None or targets.empty:
        return None
    t = targets[targets["basis"] == basis]
    key = match(loader_model, t["model"])
    if key is None:
        return None
    r = t[t["model"] == key].iloc[0]
    v = r["pdty_mud"] if cls in ("MUD", "MUDB") else r["pdty_ob"]
    return float(v) if pd.notna(v) and v > 0 else None
