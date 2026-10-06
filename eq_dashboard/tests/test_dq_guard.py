"""Rows the database would refuse, or that cleaning removes, become findings instead of a failed submit or a silent loss."""
import datetime as dt

import pandas as pd

from core import dq
from db import models as m


def _events() -> pd.DataFrame:
    n = 3
    return pd.DataFrame({
        "row_ref": [5, 6, 7], "date": [dt.date(2026, 9, 1)] * n, "shift": ["DS", None, "NS"],
        "week": ["Week 1"] * n, "seq": [0, 1, 2], "unit_id": ["A", "A", "B"], "site": ["S1"] * n,
        "hours": [1.0, 2.0, 3.0], "category": ["P"] * n,
        "reason_text": pd.Series(["x" * 130, "y", "z"], dtype="string"),
    })


def test_required_value_missing_is_left_out_as_critical():
    out, found = dq.fit_table(_events(), m.FactEvent, "Equipment Events")
    f = dq.combine(found)
    assert list(out["row_ref"]) == [5, 7]
    miss = f[f["rule"] == "required_value_missing"]
    assert list(miss["row_ref"]) == [6] and set(miss["severity"]) == {"critical"}


def test_text_longer_than_column_is_cut_with_warning():
    out, found = dq.fit_table(_events(), m.FactEvent, "Equipment Events")
    assert out["reason_text"].str.len().max() == 120
    f = dq.combine(found)
    assert f.loc[f["rule"] == "text_too_long", "severity"].tolist() == ["warn"]


def test_dropped_row_of_unknown_site_is_critical_for_every_site():
    ev = _events()
    ev.attrs["dropped"] = [(9, None), (10, "S1")]
    f = dq.combine(dq.dropped_rows(ev, "Equipment Events", "date", ["S1", "S2"]))
    assert dict(zip(f["site"], f["severity"], strict=True)) == {"S1": "critical", "S2": "critical"}
    assert "2 row(s)" in f.loc[f["site"] == "S1", "detail"].item()


def test_no_findings_when_nothing_dropped():
    assert dq.dropped_rows(_events(), "Equipment Events", "date", ["S1"]) == []
