#!/bin/sh
# Backup harian (cron di VPS): simpan 14 hari terakhir
set -e
DIR=/var/backups/eq_dashboard; mkdir -p "$DIR"
docker compose -f /opt/eq_dashboard/deploy/docker-compose.yml exec -T db \
  pg_dump -U eq_app -Fc eq_dashboard > "$DIR/eq_dashboard_$(date +%F).dump"
find "$DIR" -name '*.dump' -mtime +14 -delete
