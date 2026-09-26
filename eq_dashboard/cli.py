"""Administration commands.

    python cli.py migrate                       # create / update tables (alembic upgrade head)
    python cli.py ingest ../Data_Prod_2026-09.xlsb  # import a Data_Prod workbook (PENDING / auto-approve)
    python cli.py import-target ../Target.xlsx [--site WBK-MAS --site WBK-BAU]
    python cli.py approve <upload_site_id>      # publish one site of an upload
    python cli.py status                        # list uploads per site
    python cli.py create-admin                  # first admin (interactive, hidden password)
    python cli.py create-user budi --name "Budi" --role site_manager --site WBK-MAS
    python cli.py reset-password budi           # temporary password, must be changed at sign-in
"""
from __future__ import annotations

import argparse
import getpass
import secrets
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import select

from auth import security
from auth.access import ROLES
from core import ingest as ing
from core.targets import import_targets
from db import models as m
from db.engine import session_scope

APP_DIR = Path(__file__).resolve().parent


def cmd_migrate(_):
    sys.exit(subprocess.call([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=APP_DIR))


def cmd_ingest(a):
    path = Path(a.file)
    t = time.time()
    with session_scope() as s:
        up, sites = ing.ingest(s, path.read_bytes(), path.name, username="cli")
        rows = [(us.id, us.site_code, us.status, us.summary, us.dq_summary) for us in sites]
    print(f"Upload #{up.id} month {up.month:%Y-%m} done in {time.time() - t:.1f} s")
    for i, code, st, summ, dq in rows:
        print(f"  [{i}] {code:<10} {st:<9} unit={summ['units']:>4} OB={summ['ob_bcm']:>10,.0f} BCM "
              f"coal={summ['coal_ton']:>9,.1f} t fuel={summ['fuel_liters']:>11,.0f} L  DQ={dq}")


def cmd_import_target(a):
    with session_scope() as s:
        n = import_targets(s, Path(a.file).read_bytes(), a.site or None)
        ing.audit(s, "cli", "import_target", None, f"{a.file}: {n} rows")
    print(f"{n} target rows saved.")


def cmd_approve(a):
    with session_scope() as s:
        us = s.get(m.UploadSite, a.upload_site_id)
        if us is None:
            sys.exit("upload_site not found")
        ing.publish(s, us, None, "cli")
        print(f"{us.site_code} {us.month:%Y-%m} → PUBLISHED")


def cmd_status(_):
    with session_scope() as s:
        q = (select(m.UploadSite, m.Upload).join(m.Upload, m.Upload.id == m.UploadSite.upload_id)
             .order_by(m.Upload.id.desc(), m.UploadSite.site_code))
        for us, up in s.execute(q):
            print(f"[{us.id}] upload #{up.id} {up.filename} {us.month:%Y-%m} {us.site_code:<10} {us.status}")


def _ask_password(prompt="Password"):
    while True:
        pw = getpass.getpass(f"{prompt}: ")
        if pw != getpass.getpass("Ulangi: "):
            print("Passwords do not match, try again.")
            continue
        problem = security.password_problem(pw)
        if problem:
            print(problem)
            continue
        return pw


def cmd_create_admin(a):
    username = a.username or input("Username admin: ").strip()
    name = a.name or input("Full name: ").strip()
    pw = a.password or _ask_password()
    with session_scope() as s:
        security.create_user(s, username, name, "admin", pw, all_sites=True, must_change_password=False)
        ing.audit(s, "cli", "create_user", None, f"{username} (admin)")
    print(f"Admin '{username}' created.")


def cmd_create_user(a):
    if a.role not in ROLES:
        sys.exit(f"role must be one of: {', '.join(ROLES)}")
    temp = a.password or secrets.token_urlsafe(9) + "1a"
    with session_scope() as s:
        security.create_user(s, a.username, a.name, a.role, temp, sites=a.site or [], all_sites=a.all_sites)
        ing.audit(s, "cli", "create_user", None, f"{a.username} ({a.role}) sites={'ALL' if a.all_sites else a.site}")
    print(f"User '{a.username}' ({a.role}) created. Temporary password: {temp}  (must be changed at sign-in)")


def cmd_reset_password(a):
    temp = secrets.token_urlsafe(9) + "1a"
    with session_scope() as s:
        u = s.scalar(select(m.User).where(m.User.username == a.username))
        if u is None:
            sys.exit("user not found")
        security.set_password(s, u.id, temp, must_change=True)
        ing.audit(s, "cli", "reset_password", None, a.username)
    print(f"Temporary password for {a.username}: {temp}")


def main():
    p = argparse.ArgumentParser(description="WANPIS CLI")
    sub = p.add_subparsers(required=True)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    x = sub.add_parser("ingest"); x.add_argument("file"); x.set_defaults(fn=cmd_ingest)
    x = sub.add_parser("import-target"); x.add_argument("file"); x.add_argument("--site", action="append")
    x.set_defaults(fn=cmd_import_target)
    x = sub.add_parser("approve"); x.add_argument("upload_site_id", type=int); x.set_defaults(fn=cmd_approve)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    x = sub.add_parser("create-admin"); x.add_argument("--username"); x.add_argument("--name")
    x.add_argument("--password", help="automation only; by default it is asked without echo")
    x.set_defaults(fn=cmd_create_admin)
    x = sub.add_parser("create-user"); x.add_argument("username"); x.add_argument("--name", required=True)
    x.add_argument("--role", required=True); x.add_argument("--site", action="append")
    x.add_argument("--all-sites", action="store_true"); x.add_argument("--password")
    x.set_defaults(fn=cmd_create_user)
    x = sub.add_parser("reset-password"); x.add_argument("username"); x.set_defaults(fn=cmd_reset_password)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
