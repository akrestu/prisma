"""Model database (SQLAlchemy 2.0 declarative)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- akses
class Site(Base):
    __tablename__ = "sites"
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    target_basis: Mapped[str] = mapped_column(String(10), default="internal", server_default="internal")  # | client


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), default="")
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))  # admin | site_manager | data_officer | viewer
    all_sites: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    default_filters: Mapped[dict | None] = mapped_column(JSON)  # "Save as my default" in the sidebar


class UserSite(Base):
    __tablename__ = "user_sites"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    site_code: Mapped[str] = mapped_column(ForeignKey("sites.code"), primary_key=True)


class DisplayDevice(Base):
    __tablename__ = "display_devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    site_code: Mapped[str] = mapped_column(ForeignKey("sites.code"))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    token_enc: Mapped[str | None] = mapped_column(Text)   # same token, encrypted with the app secret (copy link)
    period: Mapped[str] = mapped_column(String(10), default="daily", server_default="daily")  # hourly..yearly
    screen: Mapped[str] = mapped_column(String(12), default="equipment", server_default="equipment")  # | hourly
    hourly_date: Mapped[dt.date | None] = mapped_column(Date)       # None = live (the shift running now)
    hourly_shift: Mapped[str | None] = mapped_column(String(2))
    review_from: Mapped[dt.date | None] = mapped_column(Date)       # None = live; else a fixed range (equipment)
    review_to: Mapped[dt.date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- upload
class Upload(Base):
    __tablename__ = "uploads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    month: Mapped[dt.date] = mapped_column(Date, index=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class UploadSite(Base):
    __tablename__ = "upload_sites"
    __table_args__ = (
        UniqueConstraint("upload_id", "site_code"),
        # the database itself guarantees one PUBLISHED version per site × month (two approvals racing)
        Index("uq_upload_sites_published", "site_code", "month", unique=True,
              postgresql_where=text("status = 'PUBLISHED'")),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    site_code: Mapped[str] = mapped_column(String(40), index=True)
    month: Mapped[dt.date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(12), index=True)  # PENDING|PUBLISHED|REJECTED|SUPERSEDED
    auto_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    dq_summary: Mapped[dict] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------- unit population (versioned master)
class PopulationVersion(Base):
    """One Unit_Population upload. It applies from `effective_from` until the next version's date."""
    __tablename__ = "population_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    effective_from: Mapped[dt.date] = mapped_column(Date, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    units: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PopulationUnit(Base):
    __tablename__ = "population_units"
    __table_args__ = (UniqueConstraint("version_id", "unit_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("population_versions.id", ondelete="CASCADE"), index=True)
    unit_id: Mapped[str] = mapped_column(String(40))
    type: Mapped[str | None] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(80))
    manufacturer: Mapped[str | None] = mapped_column(String(80))
    site: Mapped[str] = mapped_column(String(40))


# ---------------------------------------------------------------- data (semua punya upload_id, site, month)
class _Fact:
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    site: Mapped[str] = mapped_column(String(40), index=True)
    month: Mapped[dt.date] = mapped_column(Date, index=True)


class DimUnit(_Fact, Base):
    __tablename__ = "dim_unit"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    unit_id: Mapped[str] = mapped_column(String(40), index=True)
    type: Mapped[str | None] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(80))
    manufacturer: Mapped[str | None] = mapped_column(String(80))


class FactEvent(_Fact, Base):
    __tablename__ = "fact_event"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    row_ref: Mapped[int | None] = mapped_column(Integer)  # row number in the source Excel sheet
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    shift: Mapped[str] = mapped_column(String(2))
    week: Mapped[str] = mapped_column(String(8))
    seq: Mapped[int] = mapped_column(Integer)  # urutan kronologis per unit
    unit_id: Mapped[str] = mapped_column(String(40), index=True)
    type: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(80))
    operator: Mapped[str | None] = mapped_column(String(120))
    time_start: Mapped[float | None] = mapped_column(Float)  # pecahan hari
    time_end: Mapped[float | None] = mapped_column(Float)
    hours: Mapped[float] = mapped_column(Float)
    hm_start: Mapped[float | None] = mapped_column(Float)
    hm_end: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(String(12))
    category: Mapped[str] = mapped_column(String(1))
    reason_code: Mapped[int | None] = mapped_column(Integer)
    reason_text: Mapped[str | None] = mapped_column(String(120))
    down_type: Mapped[str | None] = mapped_column(String(12))


class FactStoppage(_Fact, Base):
    __tablename__ = "fact_stoppage"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    unit_id: Mapped[str] = mapped_column(String(40), index=True)
    type: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(80))
    start_date: Mapped[dt.date] = mapped_column(Date)
    start_shift: Mapped[str] = mapped_column(String(2))
    end_date: Mapped[dt.date] = mapped_column(Date)
    hours: Mapped[float] = mapped_column(Float)
    sm_hours: Mapped[float] = mapped_column(Float)
    usm_hours: Mapped[float] = mapped_column(Float)
    main_reason: Mapped[str | None] = mapped_column(String(120))
    hm_start: Mapped[float | None] = mapped_column(Float)


class FactRitase(_Fact, Base):
    __tablename__ = "fact_ritase_jam"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    row_ref: Mapped[int | None] = mapped_column(Integer)  # row number in the source Excel sheet
    site_hauler: Mapped[str] = mapped_column(String(40))
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    hour_slot: Mapped[str] = mapped_column(String(5))
    shift: Mapped[str] = mapped_column(String(2))
    hauler: Mapped[str] = mapped_column(String(40))
    hauler_model: Mapped[str | None] = mapped_column(String(80))
    muatan: Mapped[float] = mapped_column(Float)
    loader: Mapped[str] = mapped_column(String(40))
    loader_model: Mapped[str | None] = mapped_column(String(80))
    material: Mapped[str | None] = mapped_column(String(80))
    material_group: Mapped[str] = mapped_column(String(5))  # OB | CG | Other
    pit: Mapped[str | None] = mapped_column(String(120))
    disposal: Mapped[str | None] = mapped_column(String(120))
    dist_v: Mapped[float | None] = mapped_column(Float)
    dist_h: Mapped[float | None] = mapped_column(Float)
    rit: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    unit_vol: Mapped[str] = mapped_column(String(4))  # BCM | ton


class FactCoalTicket(_Fact, Base):
    __tablename__ = "fact_coal_tiket"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    row_ref: Mapped[int | None] = mapped_column(Integer)  # row number in the source Excel sheet
    site_dt: Mapped[str] = mapped_column(String(40))
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    shift: Mapped[str] = mapped_column(String(2))
    ticket_id: Mapped[str | None] = mapped_column(String(60))
    supplier: Mapped[str | None] = mapped_column(String(80))
    product: Mapped[str | None] = mapped_column(String(120))
    seam: Mapped[str | None] = mapped_column(String(40))
    dt_unit: Mapped[str | None] = mapped_column(String(40))
    loader: Mapped[str | None] = mapped_column(String(40))
    ton: Mapped[float] = mapped_column(Float)
    time_in: Mapped[dt.datetime | None] = mapped_column(DateTime)
    time_out: Mapped[dt.datetime | None] = mapped_column(DateTime)
    dist_h: Mapped[float | None] = mapped_column(Float)
    dist_v: Mapped[float | None] = mapped_column(Float)


class FactFuel(_Fact, Base):
    __tablename__ = "fact_fuel"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    row_ref: Mapped[int | None] = mapped_column(Integer)  # row number in the source Excel sheet
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    shift: Mapped[str] = mapped_column(String(2))
    time: Mapped[float | None] = mapped_column(Float)
    unit_id: Mapped[str] = mapped_column(String(40), index=True)
    type: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(80))
    liters: Mapped[float] = mapped_column(Float)
    outlier: Mapped[bool] = mapped_column(Boolean, default=False)


class FactFuelReceipt(_Fact, Base):
    __tablename__ = "fact_fuel_receipt"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    row_ref: Mapped[int | None] = mapped_column(Integer)  # row number in the source Excel sheet
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    shift: Mapped[str | None] = mapped_column(String(2))
    vendor: Mapped[str | None] = mapped_column(String(120))
    operator: Mapped[str | None] = mapped_column(String(120))
    unit: Mapped[str | None] = mapped_column(String(40))
    dn_no: Mapped[str | None] = mapped_column(String(60))
    liters: Mapped[float] = mapped_column(Float)


class DQFinding(Base):
    __tablename__ = "dq_findings"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    site: Mapped[str] = mapped_column(String(40), index=True)
    rule: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(10))  # critical | warn | info
    sheet: Mapped[str] = mapped_column(String(40))
    row_ref: Mapped[int | None] = mapped_column(Integer)
    unit_id: Mapped[str | None] = mapped_column(String(40))
    date: Mapped[dt.date | None] = mapped_column(Date)
    detail: Mapped[str] = mapped_column(Text)


# ---------------------------------------------------------------- konfigurasi
class Target(Base):
    __tablename__ = "targets"
    __table_args__ = (UniqueConstraint("site", "year", "month"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site: Mapped[str] = mapped_column(String(40))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    pa: Mapped[float | None] = mapped_column(Float)
    uoa: Mapped[float | None] = mapped_column(Float)
    mtbs: Mapped[float | None] = mapped_column(Float)
    mttr: Mapped[float | None] = mapped_column(Float)
    sched_down: Mapped[float | None] = mapped_column(Float)
    pm_accuracy: Mapped[float | None] = mapped_column(Float)
    sr: Mapped[float | None] = mapped_column(Float)          # stripping ratio target (BCM OB per t coal)
    distance: Mapped[float | None] = mapped_column(Float)    # haul distance target (m)


class PlanProduction(Base):
    __tablename__ = "plan_produksi"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site: Mapped[str] = mapped_column(String(40), index=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    date: Mapped[dt.date | None] = mapped_column(Date)  # None = plan bulanan
    ob_bcm: Mapped[float | None] = mapped_column(Float)
    coal_ton: Mapped[float | None] = mapped_column(Float)


class PMInterval(Base):
    __tablename__ = "pm_interval"
    model: Mapped[str] = mapped_column(String(80), primary_key=True)
    interval_hm: Mapped[float] = mapped_column(Float)
    tolerance_pct: Mapped[float] = mapped_column(Float, default=10.0)


class StandbyGroup(Base):
    __tablename__ = "standby_group"
    reason_code: Mapped[int] = mapped_column(Integer, primary_key=True)
    grp: Mapped[str] = mapped_column(String(10))  # client | internal


class IdAlias(Base):
    __tablename__ = "id_alias"
    alias: Mapped[str] = mapped_column(String(40), primary_key=True)
    canonical: Mapped[str] = mapped_column(String(40))


class TankSite(Base):
    __tablename__ = "tank_site"
    tank: Mapped[str] = mapped_column(String(40), primary_key=True)
    site: Mapped[str] = mapped_column(String(40))


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    username: Mapped[str | None] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(40))
    site: Mapped[str | None] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------- hourly production (flash, no approval)
class LoadFactor(Base):
    """Load per trip by material × hauler model (Link Muatan): BCM for OB, ton for coal."""
    __tablename__ = "load_factor"
    __table_args__ = (UniqueConstraint("site", "material", "hauler_model"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site: Mapped[str] = mapped_column(String(40), index=True)
    material: Mapped[str] = mapped_column(String(80))
    material_group: Mapped[str] = mapped_column(String(5))   # OB | CG
    hauler_model: Mapped[str] = mapped_column(String(80))
    muatan: Mapped[float] = mapped_column(Float)


class LoaderTarget(Base):
    """Hourly Production target of one excavator that differs from its model (BCM/h for OB, t/h for coal), per
    basis: internal (WBK) or client (BAU)."""
    __tablename__ = "loader_target"
    __table_args__ = (UniqueConstraint("site", "unit_id", "material_group", "basis"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site: Mapped[str] = mapped_column(String(40), index=True)
    unit_id: Mapped[str] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(80))
    material_group: Mapped[str] = mapped_column(String(5))
    basis: Mapped[str] = mapped_column(String(10), default="internal", server_default="internal")
    target_per_hour: Mapped[float] = mapped_column(Float)


class HourlyModelTarget(Base):
    """Hourly Production target per excavator model of a site and basis. Empty = the Production Data default."""
    __tablename__ = "hourly_model_target"
    __table_args__ = (UniqueConstraint("site", "model", "basis"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str] = mapped_column(String(80))
    basis: Mapped[str] = mapped_column(String(10))            # internal | client
    ob: Mapped[float | None] = mapped_column(Float)           # BCM/h
    mud: Mapped[float | None] = mapped_column(Float)          # BCM/h for mud / mud blending
    coal: Mapped[float | None] = mapped_column(Float)         # t/h


class HourlyShift(Base):
    __tablename__ = "hourly_shift"
    __table_args__ = (UniqueConstraint("site", "date", "shift"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site: Mapped[str] = mapped_column(String(40), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)   # production date (NS after midnight = previous day)
    shift: Mapped[str] = mapped_column(String(2))             # DS | NS
    coordinator: Mapped[str] = mapped_column(String(160), default="")
    source: Mapped[str] = mapped_column(String(10), default="web")   # web | excel
    updated_by: Mapped[str | None] = mapped_column(String(60))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                    onupdate=func.now())


class HourlyRow(Base):
    """One line of the shift sheet: an excavator loading one hauler model, with trips per hour (12 slots)."""
    __tablename__ = "hourly_row"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("hourly_shift.id", ondelete="CASCADE"), index=True)
    line: Mapped[int] = mapped_column(Integer)
    loader: Mapped[str] = mapped_column(String(40))
    loader_model: Mapped[str | None] = mapped_column(String(80))
    operator: Mapped[str | None] = mapped_column(String(120))          # loader operator name (display)
    loader_nrp: Mapped[str | None] = mapped_column(String(30))         # loader operator NRP (operator master)
    hauler: Mapped[str | None] = mapped_column(String(40))             # hauler unit ID (None on legacy lines)
    hauler_nrp: Mapped[str | None] = mapped_column(String(30))
    hauler_operator: Mapped[str | None] = mapped_column(String(120))   # hauler operator name (display)
    material: Mapped[str] = mapped_column(String(80))
    material_group: Mapped[str] = mapped_column(String(5))
    pit: Mapped[str | None] = mapped_column(String(120))
    disposal: Mapped[str | None] = mapped_column(String(120))
    distance_m: Mapped[float | None] = mapped_column(Float)
    hauler_model: Mapped[str] = mapped_column(String(80))
    muatan: Mapped[float] = mapped_column(Float)
    target_per_hour: Mapped[float | None] = mapped_column(Float)
    target_source: Mapped[str | None] = mapped_column(String(10))     # unit | hourly | default (Production Data)
    remark_code: Mapped[str | None] = mapped_column(String(10))
    remark: Mapped[str | None] = mapped_column(Text)
    r1: Mapped[float | None] = mapped_column(Float)
    r2: Mapped[float | None] = mapped_column(Float)
    r3: Mapped[float | None] = mapped_column(Float)
    r4: Mapped[float | None] = mapped_column(Float)
    r5: Mapped[float | None] = mapped_column(Float)
    r6: Mapped[float | None] = mapped_column(Float)
    r7: Mapped[float | None] = mapped_column(Float)
    r8: Mapped[float | None] = mapped_column(Float)
    r9: Mapped[float | None] = mapped_column(Float)
    r10: Mapped[float | None] = mapped_column(Float)
    r11: Mapped[float | None] = mapped_column(Float)
    r12: Mapped[float | None] = mapped_column(Float)



class HourlyRemark(Base):
    """What happened in one production hour of a fleet: hour slot 1..12, the loader, optionally one hauler."""
    __tablename__ = "hourly_remark"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("hourly_shift.id", ondelete="CASCADE"), index=True)
    slot: Mapped[int] = mapped_column(Integer)
    loader: Mapped[str] = mapped_column(String(40))
    hauler: Mapped[str | None] = mapped_column(String(40))
    code: Mapped[str | None] = mapped_column(String(10))
    remark: Mapped[str | None] = mapped_column(Text)

class Operator(Base):
    """Operator master per site: the NRP identifies a person for operator KPIs, whatever spelling the name has."""
    __tablename__ = "operators"
    __table_args__ = (UniqueConstraint("site", "nrp"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site: Mapped[str] = mapped_column(String(40), index=True)
    nrp: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(120))
    position: Mapped[str | None] = mapped_column(String(60))   # e.g. Operator Excavator, Operator DT
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class HaulerModelMap(Base):
    """Hauler model in the unit population (e.g. CWE37064R) → load-factor model (e.g. CWE370Q), per site.
    Only needed when the names differ beyond a unit suffix: '777E-KDP' finds '777E' by itself."""
    __tablename__ = "hauler_model_map"
    __table_args__ = (UniqueConstraint("site", "unit_model"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site: Mapped[str] = mapped_column(String(40), index=True)
    unit_model: Mapped[str] = mapped_column(String(80))
    load_model: Mapped[str] = mapped_column(String(80))


class LoaderModelTarget(Base):
    """Production Data default productivity of an excavator model, company-wide: internal (WBK) and client (BAU).
    BCM/h for OB and mud, t/h for coal (empty coal = the OB value). Also the fallback of Hourly Production targets."""
    __tablename__ = "loader_model_target"
    __table_args__ = (UniqueConstraint("model", "basis"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model: Mapped[str] = mapped_column(String(80))
    basis: Mapped[str] = mapped_column(String(10))            # internal | client
    pdty_ob: Mapped[float | None] = mapped_column(Float)
    pdty_mud: Mapped[float | None] = mapped_column(Float)
    pdty_coal: Mapped[float | None] = mapped_column(Float)


class HaulerModelTarget(Base):
    """Production Data default productivity of a hauler model, company-wide, per basis: BCM/h (OB), t/h (coal)."""
    __tablename__ = "hauler_model_target"
    __table_args__ = (UniqueConstraint("model", "basis"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model: Mapped[str] = mapped_column(String(80))
    basis: Mapped[str] = mapped_column(String(10))
    pdty_ob: Mapped[float | None] = mapped_column(Float)
    pdty_coal: Mapped[float | None] = mapped_column(Float)


class HaulerFactor(Base):
    """Truck factor and speeds per hauler model family (Prod_Target PDTY)."""
    __tablename__ = "hauler_factor"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family: Mapped[str] = mapped_column(String(80), unique=True)
    tf_ob: Mapped[float | None] = mapped_column(Float)
    tf_mudb: Mapped[float | None] = mapped_column(Float)
    tf_mud: Mapped[float | None] = mapped_column(Float)
    tf_coal: Mapped[float | None] = mapped_column(Float)
    sp_empty: Mapped[float | None] = mapped_column(Float)
    sp_loaded: Mapped[float | None] = mapped_column(Float)
    sp_avg: Mapped[float | None] = mapped_column(Float)
