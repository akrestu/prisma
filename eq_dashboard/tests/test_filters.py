"""Period presets, month spans, labels and filter serialisation (URL and saved default)."""
from __future__ import annotations

import datetime as dt

from core import filters as F

D = dt.date
ANCHOR, FIRST, LAST_COMPLETE = D(2026, 9, 23), D(2025, 11, 1), D(2026, 9, 22)


def rng(key, custom=None, first=FIRST):
    return F.preset_range(key, ANCHOR, first, LAST_COMPLETE, custom)


def test_presets_count_back_from_the_last_data_date():
    assert rng("last_day") == (LAST_COMPLETE, LAST_COMPLETE)
    assert rng("last7") == (D(2026, 9, 17), ANCHOR)
    assert rng("mtd") == (D(2026, 9, 1), ANCHOR)
    assert rng("last_month") == (D(2026, 8, 1), D(2026, 8, 31))
    assert rng("ytd") == (D(2026, 1, 1), ANCHOR)
    assert rng("custom", (D(2026, 9, 10), D(2026, 8, 20))) == (D(2026, 8, 20), D(2026, 9, 10))


def test_presets_are_clamped_to_available_data():
    assert rng("ytd", first=D(2026, 9, 1)) == (D(2026, 9, 1), ANCHOR)
    assert rng("last_month", first=D(2026, 9, 1)) == (ANCHOR, ANCHOR)     # no August data: never an empty range
    assert rng("custom", (D(2020, 1, 1), D(2030, 1, 1))) == (FIRST, ANCHOR)


def test_months_between_and_labels():
    assert F.months_between(D(2025, 12, 5), D(2026, 2, 3)) == [D(2025, 12, 1), D(2026, 1, 1), D(2026, 2, 1)]
    assert F.month_end(D(2024, 2, 10)) == D(2024, 2, 29)
    assert F.range_label(D(2026, 9, 1), D(2026, 9, 23)) == "1 – 23 Sep 2026"
    assert F.range_label(D(2026, 8, 20), D(2026, 9, 10)) == "20 Aug – 10 Sep 2026"
    assert F.range_label(D(2025, 12, 5), D(2026, 1, 3)) == "5 Dec 2025 – 3 Jan 2026"
    assert F.range_label(D(2026, 9, 22), D(2026, 9, 22)) == "22 Sep 2026"


def test_url_round_trip_and_hostile_input():
    state = {"f_site": ["WBK-MAS", "WBK-BAU"], "f_period": "custom", "f_range": (D(2026, 8, 20), D(2026, 9, 10)),
             "f_week": [], "f_shift": ["DS"], "f_type": None, "f_model": [], "f_unit": ["WEX019"]}
    q = F.to_query(state)
    assert q == {"site": "WBK-MAS,WBK-BAU", "period": "custom", "shift": "DS", "unit": "WEX019",
                 "from": "2026-08-20", "to": "2026-09-10"}
    back = F.from_query(q)
    assert back["f_site"] == ["WBK-MAS", "WBK-BAU"] and back["f_range"] == state["f_range"]
    bad = F.from_query({"period": "<script>", "from": "yesterday", "to": "x", "site": "A" * 5000})
    assert "f_period" not in bad and "f_range" not in bad and len(bad["f_site"][0]) == 2000


def test_saved_default_is_json_safe():
    import json
    state = {"f_site": ["WBK-MAS"], "f_period": "custom", "f_range": (D(2026, 9, 1), D(2026, 9, 15))}
    saved = json.loads(json.dumps(F.to_saved(state)))
    assert F.from_saved(saved)["f_range"] == (D(2026, 9, 1), D(2026, 9, 15))
    assert F.from_saved(None) == {}


def test_calendar_presets_follow_today_not_the_data():
    today = D(2026, 9, 30)                                     # a Wednesday
    r = lambda k: F.preset_range(k, ANCHOR, FIRST, LAST_COMPLETE, today=today)  # noqa: E731
    assert r("today") == (today, today) and r("yesterday") == (D(2026, 9, 29),) * 2
    assert r("this_week") == (D(2026, 9, 28), today)
    assert r("last_week") == (D(2026, 9, 21), D(2026, 9, 27))


def test_previous_range_for_compare():
    assert F.previous_range("mtd", D(2026, 9, 1), D(2026, 9, 23)) == (D(2026, 8, 1), D(2026, 8, 23))
    assert F.previous_range("mtd", D(2026, 3, 1), D(2026, 3, 31)) == (D(2026, 2, 1), D(2026, 2, 28))
    assert F.previous_range("last_month", D(2026, 8, 1), D(2026, 8, 31)) == (D(2026, 7, 1), D(2026, 7, 31))
    assert F.previous_range("ytd", D(2026, 1, 1), D(2026, 9, 23)) == (D(2025, 1, 1), D(2025, 9, 23))
    assert F.previous_range("last7", D(2026, 9, 17), D(2026, 9, 23)) == (D(2026, 9, 10), D(2026, 9, 16))
    assert F.previous_range("this_week", D(2026, 9, 28), D(2026, 9, 30)) == (D(2026, 9, 21), D(2026, 9, 23))


def test_compare_flag_round_trips():
    assert F.to_query({"f_cmp": True})["cmp"] == "1" and "cmp" not in F.to_query({"f_cmp": False})
    assert F.from_query({"cmp": "1"})["f_cmp"] is True
    assert F.from_saved({"f_period": "gone"}) == {}
