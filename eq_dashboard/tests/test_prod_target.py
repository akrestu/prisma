"""Productivity targets per site: excavator and hauler models, excavator overrides, internal first then client, the
wide/long grids and the targets workbook."""
from __future__ import annotations

import pandas as pd
import pytest

from core import hourly as H
from core import hourly_targets as HT
from core import prod_target as PT

MODELS = pd.DataFrame([  # a site's excavator targets per model
    ("CAT6020B", "internal", 800.0, None, None), ("CAT6020B", "client", 625.0, None, None),
    ("EX1200", "internal", 450.0, 200.0, None), ("SK330", "internal", 175.0, 100.0, 150.0),
], columns=["model", "basis", "ob", "mud", "coal"])
HAULERS = pd.DataFrame([("CAT777E", "internal", 160.0, 120.0)], columns=["model", "basis", "ob", "coal"])
OVERRIDES = pd.DataFrame([("WEX015", "6020B", "OB", "internal", 1000.0)],
                         columns=["unit_id", "model", "material_group", "basis", "target_per_hour"])


def test_names_match_by_prefix():
    assert PT.match("390FL", ["CAT390FL"]) == "CAT390FL" and PT.match("SK520XDLC-10", ["SK520", "SK5"]) == "SK520"
    assert PT.match("777E-KDP", HAULERS["model"]) == "CAT777E" and PT.match("KINGKAN 380", ["CAT777E"]) is None


def test_model_target_by_basis_and_material():
    assert PT.model_target("6020B", "OB - FreeDig", MODELS, "internal") == 800
    assert PT.model_target("6020B", "OB - FreeDig", MODELS, "client") == 625
    assert PT.model_target("EX1200-6", "OB - MUD", MODELS, "internal") == 200
    assert PT.model_target("SK330-10", "OB - Mud Blending", MODELS, "internal") == 100
    assert PT.model_target("SK330-10", "CG - Coal Getting", MODELS, "internal") == 150     # own coal value
    assert PT.model_target("6020B", "CG - Coal Getting", MODELS, "internal") == 800       # no coal value → OB
    assert PT.model_target("PC2000", "OB", MODELS, "internal") is None
    assert PT.hauler_target("777E-KDP", "OB", HAULERS, "internal") == 160
    assert PT.hauler_target("777E-KDP", "CG", HAULERS, "internal") == 120
    assert PT.hauler_target("777E-KDP", "OB", HAULERS, "client") is None


@pytest.mark.parametrize(("unit", "model", "want"), [
    ("WEX015", "CAT6020B", (1000.0, PT.UNIT)),                   # excavator override first
    ("WEX016", "CAT6020B", (800.0, PT.HOURLY)),                  # then the model: internal 800, not client 625
    ("WEX099", "PC2000", (None, None)),                          # nothing for the model: no target
])
def test_hourly_target_order(unit, model, want):
    assert PT.hourly_target(unit, model, "OB - FreeDig", OVERRIDES, MODELS) == want


def test_internal_first_client_where_internal_is_empty():
    client_only = pd.DataFrame([("6020B", "client", 700.0, None, None)], columns=["model", "basis", "ob", "mud", "coal"])
    assert PT.hourly_target("WEX016", "6020B", "OB - FreeDig", None, client_only) == (700.0, PT.HOURLY)
    client_unit = OVERRIDES.assign(basis="client", target_per_hour=640.0)
    assert PT.hourly_target("WEX015", "6020B", "OB - FreeDig", client_unit, None) == (640.0, PT.UNIT)
    assert PT.first_target(PT.hauler_target, "777E", "OB", HAULERS) == 160
    assert PT.first_target(PT.model_target, "PC2000", "OB", MODELS) is None


def test_wide_long_round_trip():
    values = {"ob": "OB BCM/h", "mud": "Mud BCM/h", "coal": "Coal t/h"}
    g = PT.wide(MODELS, values)
    assert list(g.columns) == ["model", "OB BCM/h · internal", "Mud BCM/h · internal", "Coal t/h · internal",
                               "OB BCM/h · client", "Mud BCM/h · client", "Coal t/h · client"]
    back = PT.long(pd.concat([g, pd.DataFrame({"model": ["EMPTY"]})]), values)   # a row without values is dropped
    pd.testing.assert_frame_equal(back.sort_values(["model", "basis"]).reset_index(drop=True),
                                  MODELS.sort_values(["model", "basis"]).reset_index(drop=True), check_dtype=False)


def test_resolve_takes_the_site_targets():
    lf = pd.DataFrame({"material": ["OB - FreeDig"], "material_group": ["OB"], "hauler_model": ["777E"],
                       "muatan": [41.0]})
    units = pd.DataFrame({"unit_id": ["WEX015", "WEX016", "WHT026"], "model": ["CAT6020B", "CAT6020B", "777E"],
                          "type": ["Loading", "Loading", "Hauling"], "site": ["WBK-BAU"] * 3})
    rows = pd.DataFrame({"loader": ["WEX015", "WEX016"], "hauler": ["WHT026", "WHT026"],
                         "material": ["OB - FreeDig"] * 2, "r1": [3, 2]})
    res = H.resolve(rows, lf, OVERRIDES, units, hourly_models=MODELS)
    assert res.rows["target_per_hour"].tolist() == [1000.0, 800.0]
    assert res.rows["target_source"].tolist() == ["unit", "hourly"]
    none = H.resolve(rows, lf, OVERRIDES.iloc[0:0], units)
    assert none.rows["target_per_hour"].isna().all() and any("No target for" in w for w in none.warnings)


def test_hourly_targets_workbook_round_trip():
    hourly = pd.DataFrame([("6020B", "internal", 900.0, None, None)], columns=["model", "basis", "ob", "mud", "coal"])
    data = HT.build_template("WBK-BAU", hourly, OVERRIDES, ["CAT6020B", "EX1200-6"], HAULERS, ["777E-KDP"])
    tf = HT.parse_template(data)
    assert tf.site == "WBK-BAU" and not tf.problems
    assert tf.models[["model", "basis", "ob"]].values.tolist() == [["6020B", "internal", 900.0]]
    assert tf.haulers[["model", "basis", "ob", "coal"]].values.tolist() == [["CAT777E", "internal", 160.0, 120.0]]
    assert tf.overrides[["unit_id", "material_group", "basis", "target_per_hour"]].values.tolist() == \
        [["WEX015", "OB", "internal", 1000.0]]
    assert HT.file_name("WBK-BAU") == "Productivity_targets_WBK-BAU.xlsx"
