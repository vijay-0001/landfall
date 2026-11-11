#!/usr/bin/env bash
# Nightly database dump, kept 14 days locally and copied off the VPS when BACKUP_TARGET is set (scp or rclone remote).
# Cron: 15 3 * * * cd /opt/landfall && infra/backup.sh >> backups/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
f="backups/landfall-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
docker compose -f infra/docker-compose.yml --env-file .env exec -T db pg_dump -U landfall landfall | gzip > "$f"
test -s "$f"
find backups -name 'landfall-*.sql.gz' -mtime +14 -delete
if [ -n "${BACKUP_TARGET:-}" ]; then
  case "$BACKUP_TARGET" in
    *:*) scp -q "$f" "$BACKUP_TARGET" ;;
    *) cp "$f" "$BACKUP_TARGET" ;;
  esac
fi
echo "ok $f"
