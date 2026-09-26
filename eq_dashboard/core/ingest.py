"""Upload → parse → simpan ke database per site → status PENDING / PUBLISHED (auto-approve)."""
from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from core.config import UNMAPPED
from core.io import sha256
from core.parse import Parsed, parse_eq_event
from db import models as m

PENDING, PUBLISHED, REJECTED, SUPERSEDED = "PENDING", "PUBLISHED", "REJECTED", "SUPERSEDED"


class DuplicateUpload(ValueError):
    pass


def audit(s: Session, username: str | None, action: str, site: str | None = None, detail: str = "") -> None:
    s.add(m.AuditLog(username=username, action=action, site=site, detail=detail))


def _records(df: pd.DataFrame, model, **const) -> list[dict]:
    cols = [c.key for c in model.__table__.columns if c.key != "id" and c.key not in const]
    use = [c for c in cols if c in df.columns]
    part = df[use].astype(object).where(df[use].notna(), None)
    recs = part.to_dict("records")
    for r in recs:
        r.update(const)
    return recs


def _bulk(s: Session, model, df: pd.DataFrame, **const) -> None:
    if len(df):
        s.execute(insert(model), _records(df, model, **const))


def site_summary(p: Parsed, site: str) -> dict:
    ev = p.events[p.events["site"] == site]
    rt = p.ritase[p.ritase["site"] == site]
    coal = p.coal[(p.coal["site"] == site) & ~p.coal["cancelled"]]
    return {
        "units": int(ev["unit_id"].nunique()),
        "hours": round(float(ev["hours"].sum()), 1),
        "rit": float(rt["rit"].sum()),
        "ob_bcm": round(float(rt.loc[rt["material_group"] == "OB", "volume"].sum()), 1),
        "cg_ton_ritase": round(float(rt.loc[rt["material_group"] == "CG", "volume"].sum()), 1),
        "coal_ton": round(float(coal["ton"].sum()), 2),
        "fuel_liters": float(p.fuel.loc[p.fuel["site"] == site, "liters"].sum()),
        "receipt_liters": float(p.receipt.loc[p.receipt["site"] == site, "liters"].sum()),
    }


def lookups(s: Session) -> tuple[dict[str, str], dict[str, str]]:
    alias = {a.alias.upper(): a.canonical.upper() for a in s.scalars(select(m.IdAlias))}
    tanks = {t.tank.upper(): t.site for t in s.scalars(select(m.TankSite))}
    return alias, tanks


def ingest(s: Session, data: bytes, filename: str, user_id: int | None = None,
           username: str | None = None, parsed: Parsed | None = None) -> tuple[m.Upload, list[m.UploadSite]]:
    """`parsed` boleh diisi hasil preview (parse_eq_event) agar file tidak diparse dua kali."""
    digest = sha256(data)
    if s.scalar(select(m.Upload.id).where(m.Upload.sha256 == digest)):
        raise DuplicateUpload("An identical file has already been uploaded.")
    if parsed is None:
        alias, tanks = lookups(s)
        parsed = parse_eq_event(data, alias, tanks)
    p = parsed
    month = p.month

    for code in p.sites:
        if code != UNMAPPED and s.get(m.Site, code) is None:
            s.add(m.Site(code=code, name=code))
    up = m.Upload(filename=filename, sha256=digest, month=month, uploaded_by=user_id,
                  summary={"sites": p.sites, "events": len(p.events), "dq": len(p.dq)})
    s.add(up)
    s.flush()

    c = {"upload_id": up.id, "month": month}
    _bulk(s, m.DimUnit, p.units, **c)
    _bulk(s, m.FactEvent, p.events, **c)
    _bulk(s, m.FactStoppage, p.stoppages, **c)
    _bulk(s, m.FactRitase, p.ritase, **c)
    _bulk(s, m.FactCoalTicket, p.coal[~p.coal["cancelled"]], **c)
    _bulk(s, m.FactFuel, p.fuel, **c)
    _bulk(s, m.FactFuelReceipt, p.receipt, **c)
    _bulk(s, m.DQFinding, p.dq, upload_id=up.id)

    from core.dq import summary as dq_summary
    dqs = dq_summary(p.dq)
    result = []
    for code in p.sites:
        us = m.UploadSite(upload_id=up.id, site_code=code, month=month, status=PENDING,
                          summary=site_summary(p, code), dq_summary=dqs.get(code, {}))
        s.add(us)
        result.append(us)
    s.flush()
    audit(s, username, "upload", None, f"{filename} ({month:%Y-%m}), sites: {', '.join(p.sites)}")

    for us in result:
        site = s.get(m.Site, us.site_code)
        if site and site.auto_approve and not us.dq_summary.get("critical"):
            publish(s, us, reviewer_id=None, username="auto-approve", auto=True)
    return up, result


def publish(s: Session, us: m.UploadSite, reviewer_id: int | None, username: str | None,
            auto: bool = False, comment: str = "") -> None:
    """Jadikan versi ini PUBLISHED; versi PUBLISHED sebelumnya (site + bulan sama) → SUPERSEDED."""
    s.execute(update(m.UploadSite)
              .where(m.UploadSite.site_code == us.site_code, m.UploadSite.month == us.month,
                     m.UploadSite.status == PUBLISHED, m.UploadSite.id != us.id)
              .values(status=SUPERSEDED))
    us.status, us.auto_approved = PUBLISHED, auto
    us.reviewer_id, us.reviewed_at, us.comment = reviewer_id, dt.datetime.now(dt.timezone.utc), comment
    audit(s, username, "auto_approve" if auto else "approve", us.site_code,
          f"upload #{us.upload_id} {us.month:%Y-%m}")


def reject(s: Session, us: m.UploadSite, reviewer_id: int | None, username: str | None, comment: str) -> None:
    if us.status != PENDING:
        raise ValueError(f"Only PENDING data can be rejected (current status {us.status}).")
    us.status, us.reviewer_id, us.comment = REJECTED, reviewer_id, comment
    us.reviewed_at = dt.datetime.now(dt.timezone.utc)
    audit(s, username, "reject", us.site_code, f"upload #{us.upload_id}: {comment}")


def rollback(s: Session, us: m.UploadSite, admin_id: int | None, username: str | None) -> None:
    """Kembalikan versi SUPERSEDED menjadi PUBLISHED (versi aktif sekarang → SUPERSEDED)."""
    if us.status != SUPERSEDED:
        raise ValueError("Rollback is only possible to a previously published (SUPERSEDED) version.")
    publish(s, us, admin_id, username, comment="rollback")
    audit(s, username, "rollback", us.site_code, f"to upload #{us.upload_id}")
