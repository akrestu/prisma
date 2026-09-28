"""Prod_Target: parsing PDTY, name matching, model targets by basis and material, truck factors per population."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core import hourly as H
from core import prod_target as PT

FILE = Path(__file__).resolve().parents[2] / "Prod_Target.xlsx"
pytestmark = pytest.mark.skipif(not FILE.exists(), reason="Prod_Target.xlsx not found")


@pytest.fixture(scope="module")
def pdty():
    return PT.parse(FILE.read_bytes())


def test_parse_both_blocks(pdty):
    ex, hl = pdty
    assert set(ex["basis"]) == {"internal", "client"} and ex["model"].nunique() == 12
    r = ex[(ex["model"] == "CAT390FL")].set_index("basis")
    assert (r.loc["internal", "pdty_ob"], r.loc["client", "pdty_ob"], r.loc["internal", "pdty_mud"]) == (480, 400, 200)
    f = hl.set_index("family")
    assert f.loc["CAT777E", "tf_ob"] == 41 and f.loc["CAT777E", "tf_mudb"] == 28 and f.loc["CWE280", "tf_coal"] == 22.5


def test_population_names_match_prod_target_names(pdty):
    ex, hl = pdty
    assert PT.match("390FL", ex["model"]) == "CAT390FL" and PT.match("EX1200-6", ex["model"]) == "EX1200"
    assert PT.match("SK520XDLC-10", ex["model"]) == "SK520" and PT.match("ZX470LC-5G", ex["model"]) == "ZX470"
    assert PT.match("777E-KDP", hl["family"]) == "CAT777E" and PT.match("CWE28064R", hl["family"]) == "CWE280"
    assert PT.match("KINGKAN 380", hl["family"]) is None


def test_model_target_follows_material_and_basis(pdty):
    ex, _ = pdty
    assert PT.model_target("6020B", "OB - FreeDig", ex, "internal") == 800
    assert PT.model_target("6020B", "OB - FreeDig", ex, "client") == 625
    assert PT.model_target("EX1200-6", "OB - MUD", ex, "internal") == 200
    assert PT.model_target("SK330-10", "OB - Mud Blending", ex, "internal") == 100
    assert PT.model_target("SK330-10", "CG - Coal Getting", ex, "internal") is None     # coal: per unit only


def test_truck_factors_per_population_model_with_mst_fallback(pdty):
    _, hl = pdty
    mst = pd.DataFrame([("OB - FreeDig", "7555B", 20.0), ("OB - MUD", "7555B", 12.0)],
                       columns=["material", "hauler_model", "muatan"])
    mats = ["OB - FreeDig", "OB - MUD", "OB - Mud Blending", "CG - Coal Getting"]
    rows, rep = PT.load_factors(hl, ["777E-KDP", "CWE37064R", "7555B", "KINGKAN 380"], mats, mst)
    look = rows.set_index(["material", "hauler_model"])["muatan"]
    assert look[("OB - FreeDig", "777E-KDP")] == 41 and look[("OB - Mud Blending", "777E-KDP")] == 28
    assert look[("CG - Coal Getting", "CWE37064R")] == 22.5 and ("CG - Coal Getting", "777E-KDP") not in look
    assert look[("OB - MUD", "7555B")] == 12                                     # from Mst Hourly
    src = rep.set_index("model")["source"]
    assert src["777E-KDP"] == "Prod_Target" and src["7555B"] == "Mst Hourly" and src["KINGKAN 380"] == "—"


def test_resolve_uses_model_target_unless_overridden(pdty):
    ex, _ = pdty
    lf = pd.DataFrame([("OB - MUD", "OB", "777E-KDP", 18.0)], columns=["material", "material_group", "hauler_model",
                                                                     "muatan"])
    units = pd.DataFrame([("WEX008", "Loading", "EX", "EX1200-6", "HIT", "WBK-BAU"),
                          ("WHT018", "Hauling", "DT", "777E-KDP", "CAT", "WBK-BAU")],
                         columns=["unit_id", "type", "description", "model", "manufacturer", "site"])
    rows = pd.DataFrame([{"loader": "WEX008", "hauler": "WHT018", "material": "OB - MUD", "r1": 3}])
    no_ov = pd.DataFrame(columns=["unit_id", "model", "material_group", "target_per_hour"])
    assert H.resolve(rows, lf, no_ov, units, model_targets=ex).rows.loc[0, "target_per_hour"] == 200
    assert H.resolve(rows, lf, no_ov, units, model_targets=ex, basis="client").rows.loc[0, "target_per_hour"] == 200
    ov = pd.DataFrame([("WEX008", "EX1200-6", "OB", 260.0)], columns=no_ov.columns)
    assert H.resolve(rows, lf, ov, units, model_targets=ex).rows.loc[0, "target_per_hour"] == 260
