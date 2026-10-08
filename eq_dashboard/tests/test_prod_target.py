"""Targets: Production Data defaults (excavator + hauler per model) and Hourly Production targets (per site model,
unit overrides, fallback to the default), the wide/long grids and the hourly targets workbook."""
from __future__ import annotations

import pandas as pd
import pytest

from core import hourly as H
from core import hourly_targets as HT
from core import prod_target as PT

DEFAULTS = pd.DataFrame([  # Production Data default, excavators
    ("CAT6020B", "internal", 800.0, None, None), ("CAT6020B", "client", 625.0, None, None),
    ("EX1200", "internal", 450.0, 200.0, None), ("SK330", "internal", 175.0, 100.0, 150.0),
], columns=["model", "basis", "pdty_ob", "pdty_mud", "pdty_coal"])
HAULERS = pd.DataFrame([("CAT777E", "internal", 160.0, 120.0)], columns=["model", "basis", "pdty_ob", "pdty_coal"])
HOURLY = pd.DataFrame([("6020B", "internal", 900.0, None, None)], columns=["model", "basis", "ob", "mud", "coal"])
OVERRIDES = pd.DataFrame([("WEX015", "6020B", "OB", "internal", 1000.0)],
                         columns=["unit_id", "model", "material_group", "basis", "target_per_hour"])


def test_names_match_by_prefix():
    assert PT.match("390FL", ["CAT390FL"]) == "CAT390FL" and PT.match("SK520XDLC-10", ["SK520", "SK5"]) == "SK520"
    assert PT.match("777E-KDP", HAULERS["model"]) == "CAT777E" and PT.match("KINGKAN 380", ["CAT777E"]) is None


def test_production_data_default_by_basis_and_material():
    assert PT.model_target("6020B", "OB - FreeDig", DEFAULTS, "internal") == 800
    assert PT.model_target("6020B", "OB - FreeDig", DEFAULTS, "client") == 625
    assert PT.model_target("EX1200-6", "OB - MUD", DEFAULTS, "internal") == 200
    assert PT.model_target("SK330-10", "OB - Mud Blending", DEFAULTS, "internal") == 100
    assert PT.model_target("SK330-10", "CG - Coal Getting", DEFAULTS, "internal") == 150    # own coal value
    assert PT.model_target("6020B", "CG - Coal Getting", DEFAULTS, "internal") == 800      # no coal value → OB
    assert PT.model_target("PC2000", "OB", DEFAULTS, "internal") is None
    assert PT.hauler_target("777E-KDP", "OB", HAULERS, "internal") == 160
    assert PT.hauler_target("777E-KDP", "CG", HAULERS, "internal") == 120
    assert PT.hauler_target("777E-KDP", "OB", HAULERS, "client") is None


@pytest.mark.parametrize(("unit", "model", "hourly", "want"), [
    ("WEX015", "CAT6020B", HOURLY, (1000.0, PT.UNIT)),           # unit override first
    ("WEX016", "CAT6020B", HOURLY, (900.0, PT.HOURLY)),          # then the site's hourly target of the model
    ("WEX016", "CAT6020B", None, (800.0, PT.DEFAULT)),           # then the default: internal 800, not client 625
    ("WEX099", "PC2000", HOURLY, (None, None)),                  # nothing anywhere
])
def test_hourly_target_order(unit, model, hourly, want):
    assert PT.hourly_target(unit, model, "OB - FreeDig", OVERRIDES, hourly, DEFAULTS) == want


def test_internal_first_client_where_internal_is_empty():
    client_only = pd.DataFrame([("6020B", "client", 700.0, None, None)], columns=["model", "basis", "ob", "mud", "coal"])
    both = pd.concat([client_only, HOURLY.assign(ob=850.0)], ignore_index=True)
    assert PT.hourly_target("WEX016", "6020B", "OB - FreeDig", None, client_only, DEFAULTS) == (700.0, PT.HOURLY)
    assert PT.hourly_target("WEX016", "6020B", "OB - FreeDig", None, both, DEFAULTS) == (850.0, PT.HOURLY)
    client_unit = OVERRIDES.assign(basis="client", target_per_hour=640.0)
    assert PT.hourly_target("WEX015", "6020B", "OB - FreeDig", client_unit, None, DEFAULTS) == (640.0, PT.UNIT)
    assert PT.first_target(PT.hauler_target, "777E", "OB", HAULERS) == 160
    assert PT.first_target(PT.model_target, "PC2000", "OB", DEFAULTS) is None


def test_wide_long_round_trip():
    values = {"pdty_ob": "OB BCM/h", "pdty_mud": "Mud BCM/h", "pdty_coal": "Coal t/h"}
    g = PT.wide(DEFAULTS, values)
    assert list(g.columns) == ["model", "OB BCM/h · internal", "Mud BCM/h · internal", "Coal t/h · internal",
                               "OB BCM/h · client", "Mud BCM/h · client", "Coal t/h · client"]
    back = PT.long(pd.concat([g, pd.DataFrame({"model": ["EMPTY"]})]), values)   # a row without values is dropped
    pd.testing.assert_frame_equal(back.sort_values(["model", "basis"]).reset_index(drop=True),
                                  DEFAULTS.sort_values(["model", "basis"]).reset_index(drop=True), check_dtype=False)


def test_resolve_marks_default_targets():
    lf = pd.DataFrame({"material": ["OB - FreeDig"], "material_group": ["OB"], "hauler_model": ["777E"],
                       "muatan": [41.0]})
    units = pd.DataFrame({"unit_id": ["WEX015", "WEX016", "WHT026"], "model": ["CAT6020B", "CAT6020B", "777E"],
                          "type": ["Loading", "Loading", "Hauling"], "site": ["WBK-BAU"] * 3})
    rows = pd.DataFrame({"loader": ["WEX015", "WEX016"], "hauler": ["WHT026", "WHT026"],
                         "material": ["OB - FreeDig"] * 2, "r1": [3, 2]})
    res = H.resolve(rows, lf, OVERRIDES.iloc[0:0], units, model_targets=DEFAULTS)
    assert res.rows["target_per_hour"].tolist() == [800.0, 800.0]          # no override, no hourly: internal default
    assert res.rows["target_source"].tolist() == ["default", "default"]
    assert any("Production Data default" in w for w in res.warnings)
    res = H.resolve(rows, lf, OVERRIDES, units, model_targets=DEFAULTS, hourly_models=HOURLY)
    assert res.rows["target_source"].tolist() == ["unit", "hourly"]


def test_hourly_targets_workbook_round_trip():
    data = HT.build_template("WBK-BAU", HOURLY, OVERRIDES, DEFAULTS, ["CAT6020B", "EX1200-6"])
    tf = HT.parse_template(data)
    assert tf.site == "WBK-BAU" and not tf.problems
    assert tf.models[["model", "basis", "ob"]].values.tolist() == [["6020B", "internal", 900.0]]
    assert tf.overrides[["unit_id", "material_group", "basis", "target_per_hour"]].values.tolist() == \
        [["WEX015", "OB", "internal", 1000.0]]
    assert HT.file_name("WBK-BAU") == "Hourly_Production_targets_WBK-BAU.xlsx"
