"""Role, hak akses halaman, dan pembatasan site. Semua pengecekan terjadi di server."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import UNMAPPED
from db import models as m

ADMIN, SITE_MANAGER, DATA_OFFICER, VIEWER, DISPLAY = "admin", "site_manager", "data_officer", "viewer", "display"
ROLES = [ADMIN, SITE_MANAGER, DATA_OFFICER, VIEWER]
ROLE_LABEL = {ADMIN: "Admin", SITE_MANAGER: "Site Manager", DATA_OFFICER: "Data Officer", VIEWER: "Viewer",
              DISPLAY: "Display (TV)"}

# halaman → role yang boleh membuka
PAGE_ROLES: dict[str, set[str]] = {
    "home": {ADMIN, SITE_MANAGER, DATA_OFFICER, VIEWER},
    "upload": {ADMIN, DATA_OFFICER},
    "approval": {ADMIN, SITE_MANAGER},
    "upload_history": {ADMIN, SITE_MANAGER, DATA_OFFICER},
    "account": {ADMIN, SITE_MANAGER, DATA_OFFICER, VIEWER},
    "preview_tv": {ADMIN, SITE_MANAGER},
    "display_devices": {ADMIN},
    # dashboard: semua role login
    **{k: {ADMIN, SITE_MANAGER, DATA_OFFICER, VIEWER} for k in (
        "overview", "pa_ua", "time_distribution", "reliability", "production_ob", "coal_getting", "loader_fleet",
        "fuel", "data_quality")},
    # admin
    "users_roles": {ADMIN},
    "targets_plan": {ADMIN, SITE_MANAGER},
    "pm_interval": {ADMIN},
    "sites_mapping": {ADMIN},
    "audit_log": {ADMIN, SITE_MANAGER},
}


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    name: str
    role: str
    all_sites: bool
    sites: tuple[str, ...] = field(default_factory=tuple)
    must_change_password: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == ADMIN


def load_user(s: Session, username: str) -> CurrentUser | None:
    u = s.scalar(select(m.User).where(m.User.username == username, m.User.active))
    if u is None:
        return None
    sites = tuple(s.scalars(select(m.UserSite.site_code).where(m.UserSite.user_id == u.id)))
    return CurrentUser(u.id, u.username, u.full_name, u.role, u.all_sites, sites, u.must_change_password)


def can_open(user: CurrentUser | None, page: str) -> bool:
    return user is not None and user.role in PAGE_ROLES.get(page, set())


def allowed_sites(s: Session, user: CurrentUser) -> list[str]:
    """Site yang boleh dilihat user. Admin juga melihat UNMAPPED."""
    active = list(s.scalars(select(m.Site.code).where(m.Site.active).order_by(m.Site.code)))
    if user.is_admin:
        return active + [UNMAPPED]
    if user.all_sites:
        return active
    return [c for c in active if c in user.sites]


def can_review(user: CurrentUser, site: str, sites_allowed: list[str]) -> bool:
    return user.role == ADMIN or (user.role == SITE_MANAGER and site in sites_allowed and site != UNMAPPED)


def scope_filter(df: pd.DataFrame, sites_allowed: list[str], site_col: str = "site") -> pd.DataFrame:
    """Saring baris ke site yang diizinkan. Dipanggil setelah data diambil (termasuk dari cache)."""
    return df[df[site_col].isin(sites_allowed)]
