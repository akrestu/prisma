"""Upload → parse → simpan ke database per site → status PENDING / PUBLISHED (auto-approve)."""
from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from core.config import UNMAPPED
from core.io import sha256
from core.parse import Parsed, parse_data_prod
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


def live_uploads(s: Session, digests: list[str]) -> dict[str, int]:
    """digest → upload id for files already imported and still in use. An upload whose versions were all rejected or
    superseded does not count: the same file may come in again (e.g. after fixing an alias or the unit population,
    which are applied at import)."""
    if not digests:
        return {}
    rows = s.execute(select(m.Upload.sha256, m.Upload.id, m.UploadSite.status)
                     .outerjoin(m.UploadSite, m.UploadSite.upload_id == m.Upload.id)
                     .where(m.Upload.sha256.in_(digests))).all()
    retired = {REJECTED, SUPERSEDED}
    # PENDING, PUBLISHED, or an upload without versions
    return {d: up_id for d, up_id, status in rows if status not in retired}


def month_digest(data: bytes, month) -> str:
    """Fingerprint of one month taken from a multi-month file: re-uploading the same file finds each month again."""
    return sha256(data + f"|{month:%Y-%m}".encode())


def ingest(s: Session, data: bytes, filename: str, user_id: int | None = None,
           username: str | None = None, parsed: Parsed | None = None,
           digest: str | None = None, sites: list[str] | None = None) -> tuple[m.Upload, list[m.UploadSite]]:
    """`parsed` boleh diisi hasil preview (parse_data_prod) agar file tidak diparse dua kali. For one month of a
    multi-month file pass its `parsed` month and `digest` (month_digest). `sites` limits the versions created (a
    manual edit of one site must not create partial versions for other sites its rows mention)."""
    digest = digest or sha256(data)
    if digest in live_uploads(s, [digest]):
        raise DuplicateUpload("An identical file has already been uploaded.")
    old = s.scalar(select(m.Upload).where(m.Upload.sha256 == digest))
    if old is not None:  # retired copy of the same file: free the unique digest, keep the old rows for history
        old.sha256 = sha256(f"{digest}#retired-{old.id}".encode())
        s.flush()
    if parsed is None:
        from db.repo import hourly_cutover, population_for  # local import: db.repo imports this module
        alias, tanks = lookups(s)
        parsed = parse_data_prod(data, alias, tanks, population=lambda mo: population_for(s, mo),
                                 cutover=hourly_cutover(s))
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
    for code in (c for c in p.sites if sites is None or c in sites):
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
            auto: bool = False, comment: str = "", allow_superseded: bool = False) -> None:
    """Make this version PUBLISHED; the previous PUBLISHED version of the same site + month → SUPERSEDED.

    The row is locked and its status re-checked first, so a double click or two reviewers at once cannot publish
    something that was rejected meanwhile (the partial unique index is the last line of defence)."""
    s.refresh(us, with_for_update=True)
    allowed = (PENDING, SUPERSEDED) if allow_superseded else (PENDING,)
    if us.status not in allowed:
        raise ValueError(f"{us.site_code} {us.month:%Y-%m} is already {us.status}; refresh the page.")
    s.execute(update(m.UploadSite)
              .where(m.UploadSite.site_code == us.site_code, m.UploadSite.month == us.month,
                     m.UploadSite.status == PUBLISHED, m.UploadSite.id != us.id)
              .values(status=SUPERSEDED))
    us.status, us.auto_approved = PUBLISHED, auto
    us.reviewer_id, us.reviewed_at, us.comment = reviewer_id, dt.datetime.now(dt.UTC), comment
    audit(s, username, "auto_approve" if auto else "approve", us.site_code,
          f"upload #{us.upload_id} {us.month:%Y-%m}")


def reject(s: Session, us: m.UploadSite, reviewer_id: int | None, username: str | None, comment: str) -> None:
    s.refresh(us, with_for_update=True)
    if us.status != PENDING:
        raise ValueError(f"Only PENDING data can be rejected (current status {us.status}).")
    us.status, us.reviewer_id, us.comment = REJECTED, reviewer_id, comment
    us.reviewed_at = dt.datetime.now(dt.UTC)
    audit(s, username, "reject", us.site_code, f"upload #{us.upload_id}: {comment}")


def rollback(s: Session, us: m.UploadSite, admin_id: int | None, username: str | None) -> None:
    """Kembalikan versi SUPERSEDED menjadi PUBLISHED (versi aktif sekarang → SUPERSEDED)."""
    if us.status != SUPERSEDED:
        raise ValueError("Rollback is only possible to a previously published (SUPERSEDED) version.")
    publish(s, us, admin_id, username, comment="rollback", allow_superseded=True)
    audit(s, username, "rollback", us.site_code, f"to upload #{us.upload_id}")
