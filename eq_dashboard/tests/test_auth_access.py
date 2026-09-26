"""Keamanan login, lockout, hak akses site, dan guard halaman (AppTest)."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from auth import security
from auth.access import (ADMIN, DATA_OFFICER, SITE_MANAGER, VIEWER, CurrentUser, allowed_sites, can_open,
                         can_review, load_user, scope_filter)
from core.config import UNMAPPED
from db import models as m

from .conftest import APP_DIR


def _sites(s):
    s.add_all([m.Site(code="WBK-MAS", name="MAS"), m.Site(code="WBK-BAU", name="BAU")])
    s.flush()


def test_password_policy_and_hash():
    assert security.password_problem("pendek1") is not None
    assert security.password_problem("hanyahurufsaja") is not None
    assert security.password_problem("budi12345678", "budi") is not None
    assert security.password_problem("Tambang-2026x") is None
    h = security.hash_password("Tambang-2026x")
    assert security.check_password("Tambang-2026x", h) and not security.check_password("salah", h)


def test_lockout_after_5_failures(db_session):
    s = db_session
    _sites(s)
    security.create_user(s, "budi", "Budi S", VIEWER, "Tambang-2026x", sites=["WBK-MAS"])
    s.commit()
    creds = security.credentials(s)
    creds["usernames"]["budi"]["failed_login_attempts"] = 3
    assert security.sync_failed_attempts(s, creds) == []
    assert s.query(m.User).filter_by(username="budi").one().failed_logins == 3
    creds["usernames"]["budi"]["failed_login_attempts"] = 5
    assert security.sync_failed_attempts(s, creds) == ["budi"]
    s.commit()
    u = s.query(m.User).filter_by(username="budi").one()
    assert security.is_locked(u) and u.failed_logins == 0
    assert "budi" not in security.credentials(s)["usernames"]  # cookie & login ditolak selama terkunci
    u.locked_until = security.now() - dt.timedelta(minutes=1)
    s.commit()
    assert "budi" in security.credentials(s)["usernames"]


def test_inactive_user_excluded(db_session):
    s = db_session
    security.create_user(s, "ani", "Ani", VIEWER, "Tambang-2026x")
    s.query(m.User).filter_by(username="ani").one().active = False
    s.commit()
    assert "ani" not in security.credentials(s)["usernames"]
    assert load_user(s, "ani") is None


def test_allowed_sites_per_role(db_session):
    s = db_session
    _sites(s)
    admin = CurrentUser(1, "a", "A", ADMIN, True)
    boss = CurrentUser(2, "b", "B", VIEWER, True)
    sm = CurrentUser(3, "c", "C", SITE_MANAGER, False, ("WBK-BAU",))
    assert allowed_sites(s, admin) == ["WBK-BAU", "WBK-MAS", UNMAPPED]
    assert allowed_sites(s, boss) == ["WBK-BAU", "WBK-MAS"]
    assert allowed_sites(s, sm) == ["WBK-BAU"]
    assert can_review(sm, "WBK-BAU", ["WBK-BAU"]) and not can_review(sm, "WBK-MAS", ["WBK-BAU"])
    assert not can_review(CurrentUser(4, "d", "D", DATA_OFFICER, False, ("WBK-BAU",)), "WBK-BAU", ["WBK-BAU"])
    df = pd.DataFrame({"site": ["WBK-MAS", "WBK-BAU", UNMAPPED], "v": [1, 2, 3]})
    assert scope_filter(df, ["WBK-BAU"])["v"].tolist() == [2]


def test_page_permissions():
    viewer = CurrentUser(1, "v", "V", VIEWER, False)
    officer = CurrentUser(2, "o", "O", DATA_OFFICER, False)
    assert not can_open(viewer, "upload") and not can_open(viewer, "approval")
    assert can_open(officer, "upload") and not can_open(officer, "approval")
    assert not can_open(None, "home")


@pytest.mark.parametrize("page,role,denied", [
    ("pages/data/upload.py", VIEWER, True),
    ("pages/data/approval.py", DATA_OFFICER, True),
    ("pages/data/upload_history.py", VIEWER, True),
])
def test_page_guard_blocks_wrong_role(page, role, denied):
    at = AppTest.from_file(str(APP_DIR / page), default_timeout=30)
    at.session_state["user"] = CurrentUser(9, "x", "X", role, False, ("WBK-MAS",))
    at.run()
    assert any("do not have access" in e.value for e in at.error) == denied


def test_page_guard_without_login():
    at = AppTest.from_file(str(APP_DIR / "pages/data/approval.py"), default_timeout=30)
    at.run()
    assert any("do not have access" in e.value for e in at.error)


def test_approval_page_lists_only_own_site(db_session, sample_bytes, monkeypatch):
    from core import ingest as ing
    from core.config import database_url

    s = db_session
    ing.ingest(s, sample_bytes, "Eq.Event.xlsb", username="t")
    security.create_user(s, "sm_bau", "SM BAU", SITE_MANAGER, "Tambang-2026x", sites=["WBK-BAU"])
    s.commit()
    monkeypatch.setenv("DATABASE_URL", database_url(test=True))
    at = AppTest.from_file(str(APP_DIR / "pages/data/approval.py"), default_timeout=120)
    at.session_state["user"] = load_user(s, "sm_bau")
    at.run()
    text = " ".join(md.value for md in at.markdown)
    assert "WBK-BAU" in text and "WBK-MAS" not in text and UNMAPPED not in text
    at.button(key="a_us" + str(s.query(m.UploadSite).filter_by(site_code="WBK-BAU").one().id)).click().run()
    s.expire_all()
    assert s.query(m.UploadSite).filter_by(site_code="WBK-BAU").one().status == ing.PUBLISHED
