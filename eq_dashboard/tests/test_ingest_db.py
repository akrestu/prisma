"""Ingest ke PostgreSQL test: split site, duplikat, auto-approve, approve/reject/rollback, target."""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from core import ingest as ing
from core.targets import import_targets, target_for
from db import models as m

from .conftest import TARGET


def _ingest(s, data, monkeypatch=None, digest=None):
    if digest:
        monkeypatch.setattr(ing, "sha256", lambda _b: digest)
    up, sites = ing.ingest(s, data, "Eq.Event.xlsb", username="test")
    s.commit()
    return up, {us.site_code: us for us in sites}


def test_ingest_split_and_totals(db_session, sample_bytes):
    s = db_session
    up, sites = _ingest(s, sample_bytes)
    assert set(sites) == {"UNMAPPED", "WBK-BAU", "WBK-MAS"}
    assert all(us.status == ing.PENDING for us in sites.values())
    ob = s.scalar(select(func.sum(m.FactRitase.volume)).where(m.FactRitase.material_group == "OB"))
    assert ob == pytest.approx(778796)
    assert sum(us.summary["ob_bcm"] for us in sites.values()) == pytest.approx(778796)
    assert sum(us.summary["coal_ton"] for us in sites.values()) == pytest.approx(94709.04, abs=0.05)
    assert s.scalar(select(func.count()).select_from(m.FactEvent)) == 62228
    assert sites["WBK-MAS"].dq_summary.get("critical") == 16
    with pytest.raises(ing.DuplicateUpload):
        ing.ingest(s, sample_bytes, "lagi.xlsb")


def test_auto_approve_respects_critical_dq(db_session, sample_bytes):
    s = db_session
    s.add_all([m.Site(code="WBK-MAS", name="MAS", auto_approve=True),
               m.Site(code="WBK-BAU", name="BAU", auto_approve=True)])
    s.commit()
    _, sites = _ingest(s, sample_bytes)
    assert sites["WBK-BAU"].status == ing.PUBLISHED and sites["WBK-BAU"].auto_approved
    assert sites["WBK-MAS"].status == ing.PENDING  # 16 temuan kritis → manual


def test_publish_supersede_reject_rollback(db_session, sample_bytes, monkeypatch):
    s = db_session
    _, v1 = _ingest(s, sample_bytes)
    ing.publish(s, v1["WBK-MAS"], None, "sm"); s.commit()
    _, v2 = _ingest(s, sample_bytes, monkeypatch, digest="x" * 64)
    ing.publish(s, v2["WBK-MAS"], None, "sm"); s.commit()
    s.refresh(v1["WBK-MAS"])
    assert v1["WBK-MAS"].status == ing.SUPERSEDED and v2["WBK-MAS"].status == ing.PUBLISHED
    ing.reject(s, v2["WBK-BAU"], None, "sm", "cek ulang"); s.commit()
    assert v2["WBK-BAU"].status == ing.REJECTED
    ing.rollback(s, v1["WBK-MAS"], None, "admin"); s.commit()
    s.refresh(v2["WBK-MAS"])
    assert v1["WBK-MAS"].status == ing.PUBLISHED and v2["WBK-MAS"].status == ing.SUPERSEDED
    published = s.scalar(select(func.count()).select_from(m.UploadSite)
                         .where(m.UploadSite.site_code == "WBK-MAS", m.UploadSite.status == ing.PUBLISHED))
    assert published == 1
    assert s.scalar(select(func.count()).select_from(m.AuditLog).where(m.AuditLog.action == "rollback")) == 1


@pytest.mark.skipif(not TARGET.exists(), reason="Target.xlsx not found")
def test_import_targets(db_session):
    s = db_session
    s.add_all([m.Site(code="WBK-MAS", name="MAS"), m.Site(code="WBK-BAU", name="BAU")])
    s.commit()
    n = import_targets(s, TARGET.read_bytes())
    assert n == 188
    t = target_for(s, "WBK-MAS", 2026, 9)
    assert t["pa"] is None and t["uoa"] == pytest.approx(0.6) and t["mtbs"] == 90 and t["mttr"] == 15
    assert target_for(s, "WBK-BAU", 2026, 1)["pa"] == pytest.approx(0.874565, abs=1e-6)
    # re-importing for one site overwrites instead of duplicating
    import_targets(s, TARGET.read_bytes(), ["WBK-MAS"])
    assert s.scalar(select(func.count()).select_from(m.Target)) == 188
