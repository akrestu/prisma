"""Perintah administrasi.

    python cli.py migrate                       # buat / update tabel (alembic upgrade head)
    python cli.py ingest ../Eq.Event.xlsb       # upload file Eq.Event (status PENDING / auto-approve)
    python cli.py import-target ../Target.xlsx [--site WBK-MAS --site WBK-BAU]
    python cli.py approve <upload_site_id>      # publish satu site dari sebuah upload
    python cli.py status                        # daftar upload per site
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import select

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
    print(f"Upload #{up.id} bulan {up.month:%Y-%m} selesai dalam {time.time() - t:.1f} dtk")
    for i, code, st, summ, dq in rows:
        print(f"  [{i}] {code:<10} {st:<9} unit={summ['units']:>4} OB={summ['ob_bcm']:>10,.0f} BCM "
              f"coal={summ['coal_ton']:>9,.1f} t fuel={summ['fuel_liters']:>11,.0f} L  DQ={dq}")


def cmd_import_target(a):
    with session_scope() as s:
        n = import_targets(s, Path(a.file).read_bytes(), a.site or None)
        ing.audit(s, "cli", "import_target", None, f"{a.file}: {n} baris")
    print(f"{n} baris target tersimpan.")


def cmd_approve(a):
    with session_scope() as s:
        us = s.get(m.UploadSite, a.upload_site_id)
        if us is None:
            sys.exit("upload_site tidak ditemukan")
        ing.publish(s, us, None, "cli")
        print(f"{us.site_code} {us.month:%Y-%m} → PUBLISHED")


def cmd_status(_):
    with session_scope() as s:
        q = (select(m.UploadSite, m.Upload).join(m.Upload, m.Upload.id == m.UploadSite.upload_id)
             .order_by(m.Upload.id.desc(), m.UploadSite.site_code))
        for us, up in s.execute(q):
            print(f"[{us.id}] upload #{up.id} {up.filename} {us.month:%Y-%m} {us.site_code:<10} {us.status}")


def main():
    p = argparse.ArgumentParser(description="Eq Dashboard CLI")
    sub = p.add_subparsers(required=True)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    x = sub.add_parser("ingest"); x.add_argument("file"); x.set_defaults(fn=cmd_ingest)
    x = sub.add_parser("import-target"); x.add_argument("file"); x.add_argument("--site", action="append")
    x.set_defaults(fn=cmd_import_target)
    x = sub.add_parser("approve"); x.add_argument("upload_site_id", type=int); x.set_defaults(fn=cmd_approve)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
