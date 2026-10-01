"""Query data untuk halaman. Fungsi murni (tanpa Streamlit); caching dilakukan di layer UI."""
from __future__ import annotations

import pandas as pd
from sqlalchemy import func, select
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
                   "distance_m", "hauler_model", "muatan", "target_per_hour", "target_source", "remark_code", "remark",
                   *[f"r{i}" for i in range(1, 13)]]


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
    order = (m.HourlyShift.date.desc(), m.HourlyShift.shift.desc())
    earlier = [sh for sh in s.scalars(select(m.HourlyShift).where(m.HourlyShift.site == site,
                                                                   m.HourlyShift.date <= date).order_by(*order))
               if (sh.date, sh.shift) < (date, shift)]
    if not earlier:
        return pd.DataFrame(columns=HOURLY_ROW_COLS)
    _, rows = hourly_shift(s, site, earlier[0].date, earlier[0].shift)
    return rows.assign(**{f"r{i}": None for i in range(1, 13)}, remark_code=None, remark=None)


def save_hourly(s: Session, site: str, date, shift: str, coordinator: str, rows: pd.DataFrame, username: str,
                source: str = "web") -> m.HourlyShift:
    """Replace the whole shift sheet in one transaction (the grid is always saved as a whole)."""
    from sqlalchemy import delete, insert
    sh = s.scalar(select(m.HourlyShift).where(m.HourlyShift.site == site, m.HourlyShift.date == date,
                                              m.HourlyShift.shift == shift).with_for_update())
    if sh is None:
        sh = m.HourlyShift(site=site, date=date, shift=shift)
        s.add(sh)
    sh.coordinator, sh.source, sh.updated_by = coordinator or "", source, username
    sh.updated_at = func.now()
    s.flush()
    s.execute(delete(m.HourlyRow).where(m.HourlyRow.shift_id == sh.id))
    recs = [{"shift_id": sh.id, **{c: (None if pd.isna(r.get(c)) else r.get(c)) for c in HOURLY_ROW_COLS}}
            for r in rows.to_dict("records")]
    if recs:
        s.execute(insert(m.HourlyRow), recs)
    return sh


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
    changed = 0
    for row in rows:
        value, source = hourly_target(row.loader, row.loader_model, row.material, basis, over, models, defaults)
        same = (value == row.target_per_hour or (value is None and row.target_per_hour is None))             and source == row.target_source
        if not same:
            s.execute(update(r).where(r.id == row.id).values(target_per_hour=value, target_source=source))
            changed += 1
    return {"shifts": len({row.shift_id for row in rows}), "lines": len(rows), "changed": changed}


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
