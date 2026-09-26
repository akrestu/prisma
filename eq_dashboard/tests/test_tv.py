"""TV screen: periods, payload, productivity & distance, safe rendering, Display tokens, kiosk mode."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from auth import display
from auth.access import SITE_MANAGER, VIEWER, CurrentUser
from core import ingest as ing
from core import tv
from core.periods import PERIODS, split_hourly
from core.targets import import_targets
from core.tv_render import render
from db import models as m

from .conftest import APP_DIR, TARGET


@pytest.fixture()
def published(db_session, sample_bytes):
    s = db_session
    ing.ingest(s, sample_bytes, "Eq.Event.xlsb", username="t")
    if TARGET.exists():
        import_targets(s, TARGET.read_bytes())
    ing.publish(s, s.query(m.UploadSite).filter_by(site_code="WBK-MAS").one(), None, "t")
    s.commit()
    return s


def test_split_hourly_keeps_hours(parsed):
    ev = parsed.events[parsed.events["site"] == "WBK-MAS"]
    h = split_hourly(ev)
    assert h["hours"].sum() == pytest.approx(ev["hours"].sum())
    assert h["hour_slot"].nunique() == 24
    one = pd.DataFrame({"time_start": [0.75], "hours": [12.0], "x": [1]})  # night shift 18:00–06:00
    s = split_hourly(one)
    assert s["hour_slot"].tolist()[0] == "18-19" and s["hour_slot"].tolist()[-1] == "05-06" and len(s) == 12


def test_daily_payload_mas(published):
    d = tv.build(published, "WBK-MAS", period="daily")
    k = {x.key: x for x in d.kpis}
    assert d.first_date == dt.date(2026, 9, 1) and d.last_complete == dt.date(2026, 9, 22)
    assert k["pa"].value == pytest.approx(0.7107, abs=5e-5) and k["pa"].target is None
    assert k["pa"].status == "none" and "72.7%" in k["pa"].sub
    assert k["uoa"].status == "bad" and "28.1%" in k["uoa"].sub
    assert k["mttr"].higher_better is False
    assert k["ob"].value == pytest.approx(537376) and k["coal"].value == pytest.approx(59040.28)
    assert k["pm"].value is None and k["pm"].note == "PM intervals not set"
    assert d.footer["fuel_ratio"] == pytest.approx(1.965, abs=1e-3)
    assert d.footer["units"] == 119
    assert len(d.trend) == 23 and not d.trend.iloc[-1]["complete"]
    ob = d.productivity["OB"]
    assert ob["volume"] == pytest.approx(537376)
    assert ob["dist_h"] == pytest.approx(4245, abs=1) and ob["dist_v"] == pytest.approx(137, abs=1)
    assert ob["loader_per_hour"] > ob["hauler_per_hour"] > 0
    assert d.productivity["CG"]["volume"] > 0


@pytest.mark.parametrize("period,buckets", [("hourly", 24), ("weekly", 4), ("monthly", 1), ("yearly", 1)])
def test_other_periods(published, period, buckets):
    d = tv.build(published, "WBK-MAS", period=period)
    assert d.period == period and len(d.trend) == buckets
    if period == "hourly":
        assert d.first_date == d.last_date == dt.date(2026, 9, 22)
        assert "DS:" in d.kpis[0].sub and len(d.prod) == 24
        assert d.kpis[0].value == pytest.approx(0.727, abs=5e-4)


def test_hourly_all_sites_and_missing_ticket_time(published):
    """BAU has weighbridge tickets without an entry time; hourly must not crash and totals keep them."""
    s = published
    ing.publish(s, s.query(m.UploadSite).filter_by(site_code="WBK-BAU").one(), None, "t")
    s.commit()
    for site in ("WBK-MAS", "WBK-BAU"):
        for period in PERIODS:
            d = tv.build(s, site, period=period)
            assert not d.empty and "<script" not in render(d)
    daily = {k.key: k for k in tv.build(s, "WBK-BAU", period="daily").kpis}
    assert daily["coal"].value == pytest.approx(34684.5, abs=0.1)


def test_tv_empty_until_published(published):
    assert tv.build(published, "WBK-BAU").empty  # BAU not approved yet
    assert "No published data" in render(tv.build(published, "WBK-BAU"))


@pytest.mark.parametrize("period", PERIODS)
def test_render_all_periods_safe(published, period):
    d = tv.build(published, "WBK-MAS", period=period)
    if len(d.bad_units):
        d.bad_units.loc[0, "unit"] = "<img src=x onerror=alert(1)>"
    html = render(d, kiosk=True)
    assert "<script" not in html.lower() and "<img src=x" not in html
    assert "<svg" not in html  # charts are data-URI images (st.html strips inline svg)
    assert "stHeader" in html and "IBM Plex Sans" in html
    assert "Productivity &amp; haul distance" in html


def test_display_token_lifecycle(db_session):
    s = db_session
    s.add(m.Site(code="WBK-MAS", name="MAS"))
    s.flush()
    dev, token = display.create_device(s, "Control TV", "WBK-MAS", None)
    s.commit()
    assert dev.period == "daily"
    assert token not in dev.token_hash and len(token) >= 40
    assert display.validate(s, token).site_code == "WBK-MAS"
    assert display.validate(s, "wrong" * 10) is None and display.validate(s, None) is None
    new = display.regenerate(s, dev)
    s.commit()
    assert display.validate(s, token) is None and display.validate(s, new) is not None
    dev.active = False
    s.commit()
    assert display.validate(s, new) is None


def _kiosk(monkeypatch, token):
    from core.config import database_url
    monkeypatch.setenv("DATABASE_URL", database_url(test=True))
    at = AppTest.from_file(str(APP_DIR / "app.py"), default_timeout=180)
    at.query_params["display"] = token
    at.run()
    return at


def test_kiosk_uses_device_period(published, monkeypatch):
    s = published
    dev, token = display.create_device(s, "MAS TV", "WBK-MAS", None)
    dev.period = "hourly"
    s.commit()
    at = _kiosk(monkeypatch, token)
    assert not at.exception
    assert len(at.text_input) == 0  # no login form
    html = " ".join(str(h.proto.body) for h in at.get("html"))
    assert "WBK-MAS" in html and "HOURLY" in html.upper() and "last complete day, hourly" in html
    assert "WBK-BAU" not in html


def test_kiosk_invalid_or_revoked_token(published, monkeypatch):
    s = published
    dev, token = display.create_device(s, "MAS TV", "WBK-MAS", None)
    dev.active = False
    s.commit()
    for t in (token, "x" * 43):
        at = _kiosk(monkeypatch, t)
        assert any("invalid" in e.value for e in at.error)
        assert not at.get("html")


@pytest.mark.parametrize("page,role", [("pages/tv/preview.py", VIEWER),
                                       ("pages/admin/display_devices.py", SITE_MANAGER)])
def test_tv_admin_pages_guard(page, role):
    at = AppTest.from_file(str(APP_DIR / page), default_timeout=30)
    at.session_state["user"] = CurrentUser(9, "x", "X", role, False, ("WBK-MAS",))
    at.run()
    assert any("do not have access" in e.value for e in at.error)
