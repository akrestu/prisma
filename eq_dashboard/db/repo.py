"""Query data untuk halaman. Fungsi murni (tanpa Streamlit); caching dilakukan di layer UI."""
from __future__ import annotations

import pandas as pd
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from core.ingest import PENDING, PUBLISHED
from db import models as m


def frame(s: Session, stmt) -> pd.DataFrame:
    res = s.execute(stmt)
    return pd.DataFrame(res.fetchall(), columns=list(res.keys()))


def upload_sites(s: Session, sites: list[str], statuses: list[str] | None = None,
                 uploader_id: int | None = None) -> pd.DataFrame:
    q = (select(m.UploadSite.id, m.UploadSite.upload_id, m.UploadSite.site_code.label("site"),
                m.UploadSite.month, m.UploadSite.status, m.UploadSite.auto_approved, m.UploadSite.comment,
                m.UploadSite.reviewed_at, m.UploadSite.summary, m.UploadSite.dq_summary,
                m.Upload.filename, m.Upload.uploaded_at, m.User.full_name.label("uploader"),
                m.Upload.uploaded_by)
         .join(m.Upload, m.Upload.id == m.UploadSite.upload_id)
         .outerjoin(m.User, m.User.id == m.Upload.uploaded_by)
         .where(m.UploadSite.site_code.in_(sites))
         .order_by(m.Upload.id.desc(), m.UploadSite.site_code))
    if statuses:
        q = q.where(m.UploadSite.status.in_(statuses))
    if uploader_id is not None:
        q = q.where(m.Upload.uploaded_by == uploader_id)
    return frame(s, q)


def pending_count(s: Session, sites: list[str]) -> int:
    return s.scalar(select(func.count()).select_from(m.UploadSite)
                    .where(m.UploadSite.site_code.in_(sites), m.UploadSite.status == PENDING)) or 0


def published_versions(s: Session, sites: list[str]) -> pd.DataFrame:
    """Versi PUBLISHED per site × bulan (satu baris per kombinasi)."""
    return frame(s, select(m.UploadSite.site_code.label("site"), m.UploadSite.month, m.UploadSite.upload_id,
                           m.UploadSite.reviewed_at, m.UploadSite.auto_approved)
                 .where(m.UploadSite.site_code.in_(sites), m.UploadSite.status == PUBLISHED)
                 .order_by(m.UploadSite.month.desc(), m.UploadSite.site_code))


def events(s: Session, upload_id: int, site: str) -> pd.DataFrame:
    t = m.FactEvent
    return frame(s, select(t.site, t.date, t.shift, t.week, t.seq, t.unit_id, t.type, t.model, t.hours,
                           t.hm_start, t.status, t.category, t.reason_code, t.reason_text)
                 .where(t.upload_id == upload_id, t.site == site))


def stoppages(s: Session, upload_id: int, site: str) -> pd.DataFrame:
    t = m.FactStoppage
    return frame(s, select(t.site, t.unit_id, t.type, t.model, t.start_date, t.hours, t.sm_hours, t.usm_hours,
                           t.main_reason).where(t.upload_id == upload_id, t.site == site))


def dq_findings(s: Session, upload_id: int, site: str) -> pd.DataFrame:
    t = m.DQFinding
    return frame(s, select(t.severity, t.rule, t.sheet, t.row_ref, t.unit_id, t.date, t.detail)
                 .where(t.upload_id == upload_id, t.site == site)
                 .order_by(t.severity, t.rule, t.row_ref))


# ---------------------------------------------------------------- data explorer (read-only raw tables)
EXPLORER_TABLES = {
    "Events": (m.FactEvent, "date"),
    "Stoppages": (m.FactStoppage, "start_date"),
    "Ritase (trips per hour)": (m.FactRitase, "date"),
    "Coal tickets": (m.FactCoalTicket, "date"),
    "Fuel consumption": (m.FactFuel, "date"),
    "Fuel receipts": (m.FactFuelReceipt, "date"),
    "Units (population)": (m.DimUnit, None),
    "Data quality findings": (m.DQFinding, "date"),
}
_HIDDEN = {"id", "upload_id", "month"}


def explorer_rows(s: Session, table: str, versions: list[tuple[int, str]], date_from=None, date_to=None,
                  limit: int = 200_000) -> pd.DataFrame:
    """Raw rows of one table for the given (upload_id, site) versions, optionally within a date range."""
    from sqlalchemy import and_, or_
    model, date_col = EXPLORER_TABLES[table]
    cols = [c for c in model.__table__.columns if c.key not in _HIDDEN]
    if not versions:
        return pd.DataFrame(columns=[c.key for c in cols])
    q = select(*cols).where(or_(*[and_(model.upload_id == u, model.site == st_) for u, st_ in versions]))
    if date_col and date_from is not None and date_to is not None:
        dc = getattr(model, date_col)
        q = q.where(dc >= date_from, dc <= date_to)
    order = [getattr(model, date_col)] if date_col else []
    return frame(s, q.order_by(model.site, *order, model.id).limit(limit))


# ---------------------------------------------------------------- deleting data (Admin)
PRODUCTION_TABLES = (m.FactEvent, m.FactStoppage, m.FactRitase, m.FactCoalTicket, m.FactFuel, m.FactFuelReceipt,
                     m.DimUnit, m.DQFinding)


def delete_production(s: Session, sites: list[str] | None = None, m0=None, m1=None,
                      dry_run: bool = False) -> dict[str, int]:
    """Production Data versions (every status) of `sites` (None = all) with a month in [m0, m1] (None = open),
    and every row imported with them. An upload with no site left is removed too. dry_run only counts."""
    from sqlalchemy import delete
    us = m.UploadSite
    q = select(us.id, us.upload_id, us.site_code)
    if sites is not None:
        q = q.where(us.site_code.in_(sites))
    if m0 is not None:
        q = q.where(us.month >= m0)
    if m1 is not None:
        q = q.where(us.month <= m1)
    picked = s.execute(q).all()
    by_upload: dict[int, list[str]] = {}
    for _id, up, site in picked:
        by_upload.setdefault(up, []).append(site)
    counts = {"versions": len(picked), "months": len({(up, site) for _id, up, site in picked})}
    for model in PRODUCTION_TABLES:
        n = 0
        for up, ss in by_upload.items():
            cond = (model.upload_id == up, model.site.in_(ss))
            n += (s.scalar(select(func.count()).select_from(model).where(*cond)) if dry_run
                  else s.execute(delete(model).where(*cond)).rowcount) or 0
        counts[model.__tablename__] = n
    if dry_run or not picked:
        return counts
    s.execute(delete(us).where(us.id.in_([r[0] for r in picked])))
    left = set(s.scalars(select(us.upload_id).where(us.upload_id.in_(list(by_upload)))))
    orphans = [up for up in by_upload if up not in left]
    if orphans:   # rows of sites without a version (e.g. UNMAPPED) and the upload record itself
        for model in PRODUCTION_TABLES:
            s.execute(delete(model).where(model.upload_id.in_(orphans)))
        counts["uploads"] = s.execute(delete(m.Upload).where(m.Upload.id.in_(orphans))).rowcount or 0
    return counts


def delete_hourly(s: Session, sites: list[str] | None = None, d0=None, d1=None,
                  dry_run: bool = False) -> dict[str, int]:
    """Hourly Production shifts of `sites` (None = all) dated in [d0, d1], with their lines."""
    from sqlalchemy import delete
    h = m.HourlyShift
    q = select(h.id)
    if sites is not None:
        q = q.where(h.site.in_(sites))
    if d0 is not None:
        q = q.where(h.date >= d0)
    if d1 is not None:
        q = q.where(h.date <= d1)
    ids = list(s.scalars(q))
    if dry_run:
        rows = s.scalar(select(func.count()).select_from(m.HourlyRow).where(m.HourlyRow.shift_id.in_(ids))) or 0
        return {"shifts": len(ids), "lines": rows}
    rows = s.execute(delete(m.HourlyRow).where(m.HourlyRow.shift_id.in_(ids))).rowcount or 0
    s.execute(delete(h).where(h.id.in_(ids)))
    return {"shifts": len(ids), "lines": rows}


def delete_population(s: Session, d0=None, d1=None, dry_run: bool = False) -> dict[str, int]:
    """Unit Population versions effective in [d0, d1] (None = open), with their units. Data already imported keeps
    the units it was imported with."""
    from sqlalchemy import delete
    v = m.PopulationVersion
    q = select(v.id)
    if d0 is not None:
        q = q.where(v.effective_from >= d0)
    if d1 is not None:
        q = q.where(v.effective_from <= d1)
    ids = list(s.scalars(q))
    pu = m.PopulationUnit
    if dry_run:
        return {"versions": len(ids),
                "units": s.scalar(select(func.count()).select_from(pu).where(pu.version_id.in_(ids))) or 0}
    units = s.execute(delete(pu).where(pu.version_id.in_(ids))).rowcount or 0
    s.execute(delete(v).where(v.id.in_(ids)))
    return {"versions": len(ids), "units": units}


def delete_all_data(s: Session) -> dict[str, int]:
    """Every Production Data upload and all data derived from it (users, sites, targets and settings stay)."""
    from sqlalchemy import delete
    counts = {}
    for model in (*PRODUCTION_TABLES, m.UploadSite, m.Upload):
        counts[model.__tablename__] = s.execute(delete(model)).rowcount or 0
    return counts


EXPORT_TABLES = {"units": "Units (population)", "events": "Events", "ritase": "Ritase (trips per hour)",
                 "coal": "Coal tickets", "fuel": "Fuel consumption", "receipt": "Fuel receipts"}


def export_tables(s: Session, versions: list[tuple[int, str]]) -> dict[str, pd.DataFrame]:
    """Stored tables of the given versions, keyed for core.dataprod.export_workbook."""
    return {k: explorer_rows(s, t, versions, limit=2_000_000) for k, t in EXPORT_TABLES.items()}


def latest_units(s: Session, sites: list[str]) -> pd.DataFrame:
    """Unit population of the newest PUBLISHED version per site (pre-fills the template)."""
    pub = published_versions(s, sites)
    if pub.empty:
        return pd.DataFrame()
    newest = pub.sort_values("month").groupby("site").tail(1)
    return explorer_rows(s, "Units (population)", [(int(r.upload_id), r.site) for r in newest.itertuples()])


# ---------------------------------------------------------------- unit population
def population_versions(s: Session) -> pd.DataFrame:
    v = m.PopulationVersion
    return frame(s, select(v.id, v.effective_from, v.filename, v.units, v.note, v.uploaded_at,
                           m.User.full_name.label("uploader"))
                 .outerjoin(m.User, m.User.id == v.uploaded_by).order_by(v.effective_from.desc(), v.id.desc()))


def population_units(s: Session, version_id: int) -> pd.DataFrame:
    u = m.PopulationUnit
    return frame(s, select(u.unit_id, u.type, u.description, u.model, u.manufacturer, u.site)
                 .where(u.version_id == version_id).order_by(u.site, u.type, u.unit_id))


def population_all_units(s: Session) -> pd.DataFrame:
    """Units of every version (unit_id, site, type, model, version_id): the input for the movement history."""
    u = m.PopulationUnit
    return frame(s, select(u.version_id, u.unit_id, u.site, u.type, u.model))


def population_for(s: Session, month) -> pd.DataFrame | None:
    """Units of the newest version effective on or before the last day of `month` (None if there is none)."""
    import calendar
    import datetime as dt
    last = dt.date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
    v = s.scalars(select(m.PopulationVersion).where(m.PopulationVersion.effective_from <= last)
                  .order_by(m.PopulationVersion.effective_from.desc(), m.PopulationVersion.id.desc())).first()
    if v is None:
        return _units_from_data_prod(s, last)
    units = population_units(s, v.id)
    units.attrs["source"] = f"Unit Population version #{v.id} (effective {v.effective_from:%d %b %Y})"
    return units


def save_population(s: Session, units: pd.DataFrame, effective_from, filename: str, digest: str,
                    user_id: int | None, note: str = "") -> m.PopulationVersion:
    from sqlalchemy import insert
    v = m.PopulationVersion(effective_from=effective_from, filename=filename, sha256=digest, units=len(units),
                            note=note, uploaded_by=user_id)
    s.add(v)
    s.flush()
    recs = [{"version_id": v.id, **{k: (None if pd.isna(val) else val) for k, val in r.items()}}
            for r in units[["unit_id", "type", "description", "model", "manufacturer", "site"]].to_dict("records")]
    s.execute(insert(m.PopulationUnit), recs)
    for code in sorted(set(units["site"]) - {"UNMAPPED"}):
        if s.get(m.Site, code) is None:
            s.add(m.Site(code=code, name=code))
    return v


# ---------------------------------------------------------------- hourly production
HOURLY_ROW_COLS = ["line", "loader", "loader_model", "operator", "loader_nrp", "hauler", "hauler_nrp",
                   "hauler_operator", "material", "material_group", "pit", "disposal",
                   "distance_m", "dist_v", "hauler_model", "muatan", "target_per_hour", "target_source", "remark_code",
                   "remark", *[f"r{i}" for i in range(1, 13)]]


HOURLY_REMARK_COLS = ["slot", "loader", "hauler", "code", "remark"]


def hourly_remarks(s: Session, site: str, date, shift: str) -> pd.DataFrame:
    """Remarks per hour of one shift (id, slot 1..12, loader, hauler, code, remark), in hour order."""
    r, sh = m.HourlyRemark, m.HourlyShift
    return frame(s, select(r.id, *[getattr(r, c) for c in HOURLY_REMARK_COLS]).join(sh, sh.id == r.shift_id)
                 .where(sh.site == site, sh.date == date, sh.shift == shift).order_by(r.slot, r.loader, r.id))


def add_hourly_remark(s: Session, site: str, date, shift: str, slot_from: int, slot_to: int, loader: str,
                      code: str | None, remark: str | None, username: str, hauler: str | None = None) -> int:
    """One remark for one or more consecutive hours, saved at once (no need to save the trip grid). Creates the
    shift when nothing was entered for it yet. Returns the number of hours written."""
    sh = s.scalar(select(m.HourlyShift).where(m.HourlyShift.site == site, m.HourlyShift.date == date,
                                              m.HourlyShift.shift == shift))
    if sh is None:
        sh = m.HourlyShift(site=site, date=date, shift=shift, coordinator="", source="web", updated_by=username,
                           status="DRAFT")
        s.add(sh)
        s.flush()
    else:
        _refuse_locked(sh)
    a, b = sorted((int(slot_from), int(slot_to)))
    for k in range(a, b + 1):
        s.add(m.HourlyRemark(shift_id=sh.id, slot=k, loader=loader, hauler=hauler or None, code=code or None,
                             remark=(remark or "").strip() or None))
    sh.updated_by, sh.updated_at = username, func.now()
    return b - a + 1


def delete_hourly_remarks(s: Session, ids: list[int]) -> None:
    from sqlalchemy import delete
    if ids:
        ids = [int(i) for i in ids]
        for sh in s.scalars(select(m.HourlyShift).join(m.HourlyRemark, m.HourlyRemark.shift_id == m.HourlyShift.id)
                            .where(m.HourlyRemark.id.in_(ids)).distinct()):
            _refuse_locked(sh)
        s.execute(delete(m.HourlyRemark).where(m.HourlyRemark.id.in_(ids)))


def _refuse_locked(sh: m.HourlyShift) -> None:
    from core import shift_flow as SF
    st_ = SF.state(sh.status, sh.date, SF.now())
    if st_.locked:
        raise ValueError(f"{sh.site} {sh.date:%d %b %Y} {sh.shift} is locked ({st_.label}): remarks cannot be "
                         "changed any more.")


def load_factors(s: Session, site: str) -> pd.DataFrame:
    t = m.LoadFactor
    return frame(s, select(t.material, t.material_group, t.hauler_model, t.muatan).where(t.site == site)
                 .order_by(t.material_group.desc(), t.material, t.hauler_model))


def loader_targets(s: Session, site: str) -> pd.DataFrame:
    """Hourly Production unit overrides of a site (both bases)."""
    t = m.LoaderTarget
    return frame(s, select(t.unit_id, t.model, t.material_group, t.basis, t.target_per_hour).where(t.site == site)
                 .order_by(t.basis, t.material_group.desc(), t.unit_id))


def hourly_model_targets(s: Session, site: str) -> pd.DataFrame:
    """Hourly Production targets per excavator model of a site (both bases)."""
    t = m.HourlyModelTarget
    return frame(s, select(t.model, t.basis, t.ob, t.mud, t.coal).where(t.site == site).order_by(t.model, t.basis))


def haul_destinations(s: Session, site: str) -> pd.DataFrame:
    """Destinations (Tujuan) of a site: name, material_group, active."""
    t = m.HaulDestination
    return frame(s, select(t.name, t.material_group, t.active).where(t.site == site)
                 .order_by(t.material_group.desc(), t.name))


def haul_routes(s: Session, site: str) -> pd.DataFrame:
    """Every route row of a site, history included: loader, destination, pit, dist_h, dist_v, valid_from."""
    t = m.HaulRoute
    return frame(s, select(t.loader, t.destination, t.pit, t.dist_h, t.dist_v, t.valid_from).where(t.site == site)
                 .order_by(t.loader, t.destination, t.valid_from))


def save_haul_setup(s: Session, site: str, destinations: pd.DataFrame | None = None,
                    routes: pd.DataFrame | None = None) -> dict[str, int]:
    """Replace the destinations and/or the route rows of a site (None leaves that part as it is). A destination
    used by a route is kept: it is set inactive instead of being dropped, so older routes still resolve."""
    out = {}
    if destinations is not None:
        used = set(haul_routes(s, site)["destination"]) if routes is None else set(routes["destination"])
        keep = destinations.copy()
        gone = haul_destinations(s, site)
        gone = gone[~gone["name"].str.upper().isin(set(keep["name"].str.upper())) & gone["name"].isin(used)]
        if len(gone):
            keep = pd.concat([keep, gone.assign(active=False)], ignore_index=True)
        out["destinations"] = replace_site_rows(s, m.HaulDestination, site, keep, ["name", "material_group",
                                                                                   "active"])
    if routes is not None:
        out["routes"] = replace_site_rows(s, m.HaulRoute, site, routes,
                                          ["loader", "destination", "pit", "dist_h", "dist_v", "valid_from"])
    return out


def replace_site_rows(s: Session, model, site: str, df: pd.DataFrame, cols: list[str]) -> int:
    """Replace every row of `model` for one site (small master tables edited as a whole)."""
    from sqlalchemy import delete, insert
    s.execute(delete(model).where(model.site == site))
    recs = [{"site": site, **{c: (None if pd.isna(r[c]) else r[c]) for c in cols}} for r in df.to_dict("records")]
    if recs:
        s.execute(insert(model), recs)
    return len(recs)


def hourly_shift(s: Session, site: str, date, shift: str) -> tuple[m.HourlyShift | None, pd.DataFrame]:
    sh = s.scalar(select(m.HourlyShift).where(m.HourlyShift.site == site, m.HourlyShift.date == date,
                                              m.HourlyShift.shift == shift))
    if sh is None:
        return None, pd.DataFrame(columns=HOURLY_ROW_COLS)
    r = m.HourlyRow
    rows = frame(s, select(*[getattr(r, c) for c in HOURLY_ROW_COLS]).where(r.shift_id == sh.id).order_by(r.line))
    return sh, rows


def previous_lines(s: Session, site: str, date, shift: str) -> pd.DataFrame:
    """Lines (without trips) of the latest earlier shift of the site: a starting point for the next shift."""
    h = m.HourlyShift
    prev = s.execute(select(h.date, h.shift)
                     .where(h.site == site, or_(h.date < date, and_(h.date == date, h.shift < shift)))
                     .order_by(h.date.desc(), h.shift.desc()).limit(1)).first()
    if prev is None:
        return pd.DataFrame(columns=HOURLY_ROW_COLS)
    _, rows = hourly_shift(s, site, prev.date, prev.shift)
    return rows.assign(**{f"r{i}": None for i in range(1, 13)}, remark_code=None, remark=None)


def save_hourly(s: Session, site: str, date, shift: str, coordinator: str, rows: pd.DataFrame, username: str,
                source: str = "web", remarks: pd.DataFrame | None = None, *, change_request: bool = False
                ) -> m.HourlyShift:
    """Replace the whole shift sheet in one transaction (the grid is always saved as a whole). `remarks` (per hour)
    replace the shift's remarks too; None leaves them as they are. A locked shift (approved, or past closing) is
    refused unless the save applies an approved change request; a direct save makes the shift DRAFT again."""
    from sqlalchemy import delete, insert

    from core import shift_flow as SF
    sh = s.scalar(select(m.HourlyShift).where(m.HourlyShift.site == site, m.HourlyShift.date == date,
                                              m.HourlyShift.shift == shift).with_for_update())
    if sh is None:                       # a shift never entered may still be entered late; it is locked after that
        sh = m.HourlyShift(site=site, date=date, shift=shift, status=SF.DRAFT)
        s.add(sh)
    elif not change_request:
        now_state = SF.state(sh.status, date, SF.now())
        if now_state.locked:
            raise ValueError(f"{site} {date:%d %b %Y} {shift} is locked ({now_state.label}): send a change request "
                             "instead.")
        sh.status = SF.after_save(sh.status)
    sh.coordinator, sh.source, sh.updated_by = coordinator or "", source, username
    sh.updated_at = func.now()
    s.flush()
    s.execute(delete(m.HourlyRow).where(m.HourlyRow.shift_id == sh.id))
    recs = [{"shift_id": sh.id, **{c: (None if pd.isna(r.get(c)) else r.get(c)) for c in HOURLY_ROW_COLS}}
            for r in rows.to_dict("records")]
    if recs:
        s.execute(insert(m.HourlyRow), recs)
    if remarks is not None:
        s.execute(delete(m.HourlyRemark).where(m.HourlyRemark.shift_id == sh.id))
        rr = [{"shift_id": sh.id, **{c: (None if pd.isna(r.get(c)) else r.get(c)) for c in HOURLY_REMARK_COLS}}
              for r in remarks.to_dict("records")]
        for r in rr:
            r["slot"] = int(r["slot"])
        if rr:
            s.execute(insert(m.HourlyRemark), rr)
    return sh


# ---------------------------------------------------------------- approval per shift (core.shift_flow)
def _locked_shift(s: Session, shift_id: int) -> m.HourlyShift:
    sh = s.scalar(select(m.HourlyShift).where(m.HourlyShift.id == int(shift_id)).with_for_update())
    if sh is None:
        raise ValueError(f"Shift #{shift_id} no longer exists.")
    return sh


def submit_shift(s: Session, site: str, date, shift: str, username: str) -> m.HourlyShift:
    """Send a saved shift to the Site Manager."""
    from core import shift_flow as SF
    sh = s.scalar(select(m.HourlyShift).where(m.HourlyShift.site == site, m.HourlyShift.date == date,
                                              m.HourlyShift.shift == shift).with_for_update())
    if sh is None or not SF.state(sh.status, date, SF.now()).can_submit:
        raise ValueError(f"{site} {date:%d %b %Y} {shift} cannot be submitted now"
                         + (f" ({SF.LABEL.get(sh.status, sh.status)})." if sh is not None else ": save it first."))
    sh.status, sh.submitted_by, sh.submitted_at = SF.SUBMITTED, username, func.now()
    return sh


def review_shift(s: Session, shift_id: int, approve: bool, username: str, note: str = "") -> m.HourlyShift:
    """Approve or reject a submitted shift (a reason is needed to reject). The caller checks the reviewer's site."""
    from core import shift_flow as SF
    sh = _locked_shift(s, shift_id)
    if sh.status != SF.SUBMITTED:
        raise ValueError(f"{sh.site} {sh.date:%d %b %Y} {sh.shift} is no longer waiting for approval "
                         f"({SF.LABEL.get(sh.status, sh.status)}).")
    if not approve and not (note or "").strip():
        raise ValueError("Enter a reason for rejecting.")
    sh.status = SF.APPROVED if approve else SF.REJECTED
    sh.reviewed_by, sh.reviewed_at, sh.review_note = username, func.now(), (note or "").strip() or None
    return sh


def shifts_waiting(s: Session, sites: list[str]) -> pd.DataFrame:
    """Submitted shifts of the sites, oldest first."""
    h = m.HourlyShift
    return frame(s, select(h.id, h.site, h.date, h.shift, h.coordinator, h.submitted_by, h.submitted_at,
                           h.updated_by, h.updated_at)
                 .where(h.site.in_(sites), h.status == "SUBMITTED").order_by(h.date, h.shift, h.site))


def _rows_json(rows: pd.DataFrame) -> list[dict]:
    import json
    return json.loads(rows.reindex(columns=HOURLY_ROW_COLS).to_json(orient="records", date_format="iso"))


def request_change(s: Session, site: str, date, shift: str, coordinator: str, rows: pd.DataFrame, reason: str,
                   username: str) -> m.HourlyChangeRequest:
    """New sheet for a locked shift, waiting for the Site Manager. Sending again replaces the open request."""
    from core import shift_flow as SF
    if not (reason or "").strip():
        raise ValueError("Enter the reason for the change.")
    sh = s.scalar(select(m.HourlyShift).where(m.HourlyShift.site == site, m.HourlyShift.date == date,
                                              m.HourlyShift.shift == shift).with_for_update())
    if sh is None or not SF.state(sh.status, date, SF.now()).locked:
        raise ValueError(f"{site} {date:%d %b %Y} {shift} is not locked: save it directly.")
    cr = pending_change(s, sh.id)
    if cr is None:
        cr = m.HourlyChangeRequest(shift_id=sh.id, status=SF.PENDING)
        s.add(cr)
    cr.coordinator, cr.rows, cr.reason = coordinator or "", _rows_json(rows), reason.strip()
    cr.requested_by, cr.requested_at = username, func.now()
    s.flush()
    return cr


def pending_change(s: Session, shift_id: int) -> m.HourlyChangeRequest | None:
    c = m.HourlyChangeRequest
    return s.scalar(select(c).where(c.shift_id == int(shift_id), c.status == "PENDING"))


def change_requests(s: Session, sites: list[str]) -> pd.DataFrame:
    """Open change requests of the sites, oldest first, with their shift."""
    c, h = m.HourlyChangeRequest, m.HourlyShift
    return frame(s, select(c.id, c.shift_id, h.site, h.date, h.shift, h.status.label("shift_status"), c.reason,
                           c.requested_by, c.requested_at, c.coordinator)
                 .join(h, h.id == c.shift_id).where(h.site.in_(sites), c.status == "PENDING")
                 .order_by(c.requested_at))


def change_rows(s: Session, request_id: int) -> pd.DataFrame:
    cr = s.get(m.HourlyChangeRequest, int(request_id))
    return pd.DataFrame(cr.rows or [], columns=HOURLY_ROW_COLS) if cr else pd.DataFrame(columns=HOURLY_ROW_COLS)


def decide_change(s: Session, request_id: int, approve: bool, username: str, note: str = "") -> m.HourlyShift:
    """Apply (approve) or refuse a change request. Applying replaces the shift's lines; its status stays as it was.
    The caller checks the reviewer's site."""
    from core import shift_flow as SF
    cr = s.scalar(select(m.HourlyChangeRequest).where(m.HourlyChangeRequest.id == int(request_id))
                  .with_for_update())
    if cr is None or cr.status != SF.PENDING:
        raise ValueError(f"Change request #{request_id} is no longer open.")
    if not approve and not (note or "").strip():
        raise ValueError("Enter a reason for rejecting.")
    sh = _locked_shift(s, cr.shift_id)
    if approve:
        save_hourly(s, sh.site, sh.date, sh.shift, cr.coordinator, change_rows(s, cr.id), cr.requested_by,
                    sh.source, change_request=True)
    cr.status = SF.APPROVED if approve else SF.REJECTED
    cr.decided_by, cr.decided_at, cr.decision_note = username, func.now(), (note or "").strip() or None
    return sh


def hourly_waiting_count(s: Session, sites: list[str]) -> int:
    """Shifts and change requests waiting for a Site Manager."""
    h, c = m.HourlyShift, m.HourlyChangeRequest
    a = s.scalar(select(func.count()).select_from(h).where(h.site.in_(sites), h.status == "SUBMITTED")) or 0
    b = s.scalar(select(func.count()).select_from(c).join(h, h.id == c.shift_id)
                 .where(h.site.in_(sites), c.status == "PENDING")) or 0
    return int(a) + int(b)


def last_hourly_shift(s: Session, sites: list[str]) -> tuple[str, object, str] | None:
    """(site, date, shift) of the newest Hourly Production shift within the sites."""
    h = m.HourlyShift
    row = s.execute(select(h.site, h.date, h.shift).where(h.site.in_(sites))
                    .order_by(h.date.desc(), h.shift.desc()).limit(1)).first()
    return tuple(row) if row else None


def recalc_hourly_targets(s: Session, site: str, d0, d1) -> dict[str, int]:
    """Apply the current Hourly Production targets to the saved shifts of a site in [d0, d1] (a shift keeps the
    target it was saved with until this runs). Returns shifts, lines and lines whose target changed."""
    from sqlalchemy import update

    from core.prod_target import hourly_target
    r, h = m.HourlyRow, m.HourlyShift
    rows = s.execute(select(r.id, r.loader, r.loader_model, r.material, r.target_per_hour, r.target_source, r.shift_id)
                     .join(h, h.id == r.shift_id).where(h.site == site, h.date >= d0, h.date <= d1)).all()
    basis, over = site_basis(s, site), loader_targets(s, site)
    models, defaults = hourly_model_targets(s, site), model_targets(s)
    updates = []
    for row in rows:
        value, source = hourly_target(row.loader, row.loader_model, row.material, basis, over, models, defaults)
        if value != row.target_per_hour or source != row.target_source:
            updates.append({"id": row.id, "target_per_hour": value, "target_source": source})
    if updates:
        s.execute(update(r), updates)   # one bulk UPDATE by primary key
    return {"shifts": len({row.shift_id for row in rows}), "lines": len(rows), "changed": len(updates)}


def hourly_range(s: Session, sites: list[str], d0, d1) -> pd.DataFrame:
    """All hourly rows of the sites between two production dates, with their shift header."""
    r, h = m.HourlyRow, m.HourlyShift
    return frame(s, select(h.site, h.date, h.shift, h.coordinator, h.updated_at, h.updated_by,
                           *[getattr(r, c) for c in HOURLY_ROW_COLS])
                 .join(h, h.id == r.shift_id)
                 .where(h.site.in_(sites), h.date >= d0, h.date <= d1).order_by(h.date, h.shift, r.line))


def operators(s: Session, site: str, active_only: bool = True) -> pd.DataFrame:
    o = m.Operator
    q = select(o.nrp, o.name, o.position, o.active).where(o.site == site).order_by(o.name)
    if active_only:
        q = q.where(o.active)
    return frame(s, q)


def _units_from_data_prod(s: Session, last) -> pd.DataFrame | None:
    """Fallback while no Unit_Population version exists: the units of the newest PUBLISHED Data_Prod per site."""
    us, du = m.UploadSite, m.DimUnit
    pub = frame(s, select(us.site_code.label("site"), us.upload_id, us.month)
                .where(us.status == "PUBLISHED", us.month <= last).order_by(us.month.desc()))
    if pub.empty:
        return None
    newest = pub.groupby("site").head(1)
    parts = [frame(s, select(du.unit_id, du.type, du.description, du.model, du.manufacturer, du.site)
                   .where(du.upload_id == int(r.upload_id), du.site == r.site)) for r in newest.itertuples()]
    units = pd.concat(parts, ignore_index=True).drop_duplicates("unit_id") if parts else pd.DataFrame()
    if units.empty:
        return None
    units.attrs["source"] = "units of the latest published Production Data (no Unit Population version yet)"
    # only sites that already have published data are in it: a file's own unit sheet is preferred (core.parse)
    units.attrs["fallback"] = True
    return units


def hauler_model_map(s: Session, site: str) -> dict[str, str]:
    t = m.HaulerModelMap
    return dict(s.execute(select(t.unit_model, t.load_model).where(t.site == site)).all())


# ---------------------------------------------------------------- Production Data default productivity
def model_targets(s: Session) -> pd.DataFrame:
    """Production Data default productivity of excavator models (company-wide, both bases)."""
    t = m.LoaderModelTarget
    return frame(s, select(t.model, t.basis, t.pdty_ob, t.pdty_mud, t.pdty_coal).order_by(t.model, t.basis))


def hauler_targets(s: Session) -> pd.DataFrame:
    """Production Data default productivity of hauler models (company-wide, both bases)."""
    t = m.HaulerModelTarget
    return frame(s, select(t.model, t.basis, t.pdty_ob, t.pdty_coal).order_by(t.model, t.basis))


def site_basis(s: Session, site: str) -> str:
    return s.scalar(select(m.Site.target_basis).where(m.Site.code == site)) or "internal"


def _replace(s: Session, model, df: pd.DataFrame, cols: list[str], **where) -> int:
    from sqlalchemy import delete, insert
    q = delete(model)
    for k, v in where.items():
        q = q.where(getattr(model, k) == v)
    s.execute(q)
    recs = df[cols].astype(object).where(df[cols].notna(), None).to_dict("records") if len(df) else []
    for r in recs:
        r.update(where)
    if recs:
        s.execute(insert(model), recs)
    return len(recs)


def save_default_targets(s: Session, loaders: pd.DataFrame | None = None, haulers: pd.DataFrame | None = None
                         ) -> dict[str, int]:
    """Replace the Production Data defaults (a table passed as None is left as it is)."""
    out = {}
    if loaders is not None:
        out["loaders"] = _replace(s, m.LoaderModelTarget, loaders, ["model", "basis", "pdty_ob", "pdty_mud",
                                                                    "pdty_coal"])
    if haulers is not None:
        out["haulers"] = _replace(s, m.HaulerModelTarget, haulers, ["model", "basis", "pdty_ob", "pdty_coal"])
    return out


def save_hourly_targets(s: Session, site: str, models: pd.DataFrame | None = None,
                        overrides: pd.DataFrame | None = None) -> dict[str, int]:
    """Replace a site's Hourly Production targets per model and/or its unit overrides."""
    out = {}
    if models is not None:
        out["models"] = _replace(s, m.HourlyModelTarget, models, ["model", "basis", "ob", "mud", "coal"], site=site)
    if overrides is not None:
        out["overrides"] = _replace(s, m.LoaderTarget, overrides,
                                    ["unit_id", "model", "material_group", "basis", "target_per_hour"], site=site)
    return out
