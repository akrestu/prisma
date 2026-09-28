#!/bin/sh
# Daily backup (cron on the VPS), keeps the last 14 days:
#   15 2 * * * /opt/eq_dashboard/deploy/backup.sh >> /var/log/wanpis-backup.log 2>&1
set -eu
APP=/opt/eq_dashboard
DIR=/var/backups/eq_dashboard
DC="docker compose -f $APP/deploy/docker-compose.yml --env-file $APP/deploy/.env"
mkdir -p "$DIR"
OUT="$DIR/eq_dashboard_$(date +%F).dump"
TMP="$OUT.partial"
# write to a temporary file, check it can be read back, and only then keep it:
# a failed or cut-off dump must never replace a good one or count as a backup
$DC exec -T db pg_dump -U eq_app -Fc eq_dashboard > "$TMP"
$DC exec -T db pg_restore --list < "$TMP" > /dev/null
mv "$TMP" "$OUT"
find "$DIR" -name 'eq_dashboard_*.dump' -mtime +14 -delete
echo "$(date '+%F %T') backup ok: $OUT ($(du -h "$OUT" | cut -f1))"
