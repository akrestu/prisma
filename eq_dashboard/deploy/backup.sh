#!/bin/sh
# Daily backup (cron on the VPS), keeps the last 14 days:
#   15 2 * * * /opt/eq_dashboard/deploy/backup.sh >> /var/log/wanpis-backup.log 2>&1
# Every run records backup_ok / backup_failed in the app's audit log, so Admins see a stale or failed backup
# on the Data status page without logging in to the server.
set -eu
APP=/opt/eq_dashboard
DIR=/var/backups/eq_dashboard
DC="docker compose -f $APP/deploy/docker-compose.yml --env-file $APP/deploy/.env"
OUT="$DIR/eq_dashboard_$(date +%F).dump"
TMP="$OUT.partial"

record() {  # record <action> <detail>
  $DC exec -T db psql -q -U eq_app -d eq_dashboard -v ON_ERROR_STOP=1 \
    -c "INSERT INTO audit_log (username, action, detail) VALUES ('system', '$1', '$2')" >/dev/null 2>&1 || true
}
trap 'rc=$?; if [ $rc -ne 0 ]; then rm -f "$TMP"; record backup_failed "exit code $rc on $(hostname)"; \
      echo "$(date "+%F %T") backup FAILED (exit $rc)"; fi' EXIT

mkdir -p "$DIR"
# write to a temporary file, check it can be read back, and only then keep it:
# a failed or cut-off dump must never replace a good one or count as a backup
$DC exec -T db pg_dump -U eq_app -Fc eq_dashboard > "$TMP"
$DC exec -T db pg_restore --list < "$TMP" > /dev/null
mv "$TMP" "$OUT"
find "$DIR" -name 'eq_dashboard_*.dump' -mtime +14 -delete
SIZE=$(du -h "$OUT" | cut -f1)
record backup_ok "$(basename "$OUT") $SIZE"
echo "$(date '+%F %T') backup ok: $OUT ($SIZE)"
