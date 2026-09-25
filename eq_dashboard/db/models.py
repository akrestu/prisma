"""Model database (SQLAlchemy 2.0 declarative)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, func,
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
    __table_args__ = (UniqueConstraint("upload_id", "site_code"),)
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
