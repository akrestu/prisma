"""Every downloadable workbook can be imported back as it is (round trip), and names its own dataset and version."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from core import dataprod, load_factors, population, targets
from core import hourly as H
from core import hourly_targets as HT
from core.io import read_workbook
from core.validate import TEMPLATE_VERSION, template_meta

UNITS = pd.DataFrame({"unit_id": ["WEX015", "WHT026"], "type": ["Loading", "Hauling"], "description": [None, None],
                      "model": ["CAT6020B", "777E"], "manufacturer": ["CAT", "CAT"], "site": ["WBK-BAU", "WBK-BAU"]})
LOAD = pd.DataFrame({"material": ["OB - FreeDig"], "material_group": ["OB"], "hauler_model": ["777E"],
                     "muatan": [41.0]})
OVER = pd.DataFrame({"unit_id": ["WEX015"], "model": ["CAT6020B"], "material_group": ["OB"], "basis": ["internal"],
                     "target_per_hour": [900.0]})
NO_MODELS = pd.DataFrame(columns=["model", "basis", "ob", "mud", "coal"])


@pytest.mark.parametrize(("build", "dataset", "version"), [
    (lambda: dataprod.build_template(["WBK-BAU"]), "Production Data", str(TEMPLATE_VERSION)),
    (lambda: population.build_template(["WBK-BAU"], UNITS, dt.date(2026, 10, 1)), "Unit Population", "1"),
    (lambda: H.build_template("WBK-BAU", dt.date(2026, 10, 1), "DS", LOAD, OVER), "Hourly Production", "1"),
    (lambda: HT.build_template("WBK-BAU", NO_MODELS, OVER, ["CAT6020B"]), "Productivity targets", "1"),
    (lambda: load_factors.build_template("WBK-BAU", LOAD, ["777E"]), "Load Factors", "1"),
    (lambda: targets.build_template("WBK-BAU", 2026, pd.DataFrame(columns=["month"])), "Production targets", "1"),
])
def test_each_workbook_names_its_dataset_and_version(build, dataset, version):
    meta = template_meta(read_workbook(build()))
    assert meta["dataset"] == dataset and meta["template_version"] == version


def test_unit_population_download_imports_back():
    pf = population.parse_population(population.build_template(["WBK-BAU"], UNITS, dt.date(2026, 10, 1)))
    assert sorted(pf.units["unit_id"]) == ["WEX015", "WHT026"] and not pf.duplicates and not pf.without_site


def test_targets_workbook_round_trip_keeps_fractions_and_hourly_screen_targets():
    cur = pd.DataFrame({"month": [1, 2], "pa": [0.85, 0.9], "uoa": [0.7, None], "mtbs": [40.0, None],
                        "mttr": [None, None], "sched_down": [None, None], "pm_accuracy": [None, None],
                        "sr": [12.8, None], "distance": [2500.0, None]})
    data = targets.build_template("WBK-BAU", 2026, cur)
    df = targets.read_target_file(data)
    assert len(df) == 12 and set(df["site"]) == {"WBK-BAU"} and set(df["year"]) == {2026}
    jan = df[df["month"] == 1].iloc[0]
    assert jan["pa"] == pytest.approx(0.85) and jan["sr"] == pytest.approx(12.8) and jan["distance"] == 2500
    assert pd.isna(df[df["month"] == 3].iloc[0]["pa"])                 # empty month stays without a target
    assert targets.file_name("WBK-BAU", 2026) == "Production_Targets_WBK-BAU_2026.xlsx"


def test_old_target_file_without_hourly_columns_is_read():
    import io
    buf = io.BytesIO()
    pd.DataFrame({"Year": [2026], "Month": [9], "Target PA": [0.85]}).to_excel(buf, index=False)
    df = targets.read_target_file(buf.getvalue())
    assert "sr" not in df.columns and df["pa"].iloc[0] == pytest.approx(0.85)   # sr is then left untouched
