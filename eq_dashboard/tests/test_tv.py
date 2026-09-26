"""Layar TV: paket data, render aman, token Display, dan mode kiosk."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from auth import display
from auth.access import SITE_MANAGER, VIEWER, CurrentUser
from core import ingest as ing
from core import tv
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


def test_tv_payload_mas(published):
    d = tv.build(published, "WBK-MAS")
    k = {x.key: x for x in d.kpis}
    assert d.month == dt.date(2026, 9, 1) and d.last_complete == dt.date(2026, 9, 22)
    assert k["pa"].value == pytest.approx(0.7107, abs=5e-5) and k["pa"].target is None
    assert k["pa"].status == "none" and "72,7%" in k["pa"].last
    assert k["uoa"].status == "bad" and "28,1%" in k["uoa"].last
    assert k["mttr"].higher_better is False
    assert k["ob"].value == pytest.approx(537376) and k["coal"].value == pytest.approx(59040.28)
    assert k["pm"].value is None and k["pm"].note == "interval PM belum diisi"
    assert d.footer["fuel_ratio"] == pytest.approx(1.965, abs=1e-3)
    assert d.footer["units"] == 119
    assert not d.daily.set_index("date").loc[dt.date(2026, 9, 23), "complete"]


def test_tv_empty_until_published(published):
    assert tv.build(published, "WBK-BAU").empty  # BAU belum di-approve
    html = render(tv.build(published, "WBK-BAU"))
    assert "Belum ada data yang dipublikasikan" in html


def test_render_has_no_script_and_escapes(published):
    d = tv.build(published, "WBK-MAS")
    d.bad_units.loc[0, "unit"] = "<img src=x onerror=alert(1)>"
    html = render(d, kiosk=True)
    assert "<script" not in html.lower() and "<img" not in html
    assert "&lt;img" in html
    assert "stHeader" in html  # CSS kiosk menyembunyikan header Streamlit
    assert "stHeader" not in render(d, kiosk=False)


def test_display_token_lifecycle(db_session):
    s = db_session
    s.add(m.Site(code="WBK-MAS", name="MAS"))
    s.flush()
    dev, token = display.create_device(s, "TV kontrol", "WBK-MAS", None)
    s.commit()
    assert token not in dev.token_hash and len(token) >= 40
    assert display.validate(s, token).site_code == "WBK-MAS"
    assert display.validate(s, "salah" * 10) is None and display.validate(s, None) is None
    new = display.regenerate(s, dev)
    s.commit()
    assert display.validate(s, token) is None and display.validate(s, new) is not None
    dev.active = False
    s.commit()
    assert display.validate(s, new) is None


def _kiosk(monkeypatch, token):
    from core.config import database_url
    monkeypatch.setenv("DATABASE_URL", database_url(test=True))
    at = AppTest.from_file(str(APP_DIR / "app.py"), default_timeout=120)
    at.query_params["display"] = token
    at.run()
    return at


def test_kiosk_valid_token_shows_tv_without_login(published, monkeypatch):
    s = published
    _, token = display.create_device(s, "TV MAS", "WBK-MAS", None)
    s.commit()
    at = _kiosk(monkeypatch, token)
    assert not at.exception
    assert len(at.text_input) == 0  # tidak ada form login
    html = " ".join(str(h.proto.body) for h in at.get("html"))
    assert "WBK-MAS" in html and "Trend harian" in html and "WBK-BAU" not in html


def test_kiosk_invalid_or_revoked_token(published, monkeypatch):
    s = published
    dev, token = display.create_device(s, "TV MAS", "WBK-MAS", None)
    dev.active = False
    s.commit()
    for t in (token, "x" * 43):
        at = _kiosk(monkeypatch, t)
        assert any("tidak valid" in e.value for e in at.error)
        assert not at.get("html")


@pytest.mark.parametrize("page,role", [("pages/tv/preview.py", VIEWER),
                                       ("pages/admin/display_devices.py", SITE_MANAGER)])
def test_tv_admin_pages_guard(page, role):
    at = AppTest.from_file(str(APP_DIR / page), default_timeout=30)
    at.session_state["user"] = CurrentUser(9, "x", "X", role, False, ("WBK-MAS",))
    at.run()
    assert any("tidak punya akses" in e.value for e in at.error)
