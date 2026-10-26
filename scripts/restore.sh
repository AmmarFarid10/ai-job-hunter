#!/usr/bin/env bash
# Restore only to an offline, empty production database and artifact volume.
set -euo pipefail
cd "$(dirname "$0")/.."
restore_source="${1:?Usage: RESTORE_CONFIRM_EMPTY=true scripts/restore.sh /private/backup-directory}"
if [ "${RESTORE_CONFIRM_EMPTY:-}" != true ]; then echo "Set RESTORE_CONFIRM_EMPTY=true after selecting a fresh empty target"; exit 1; fi
uv run python scripts/verify_backup.py "$restore_source"
production_compose=(docker compose --env-file .env.production -f compose.production.yaml)
case "$("${production_compose[@]}" ps --status running --services)" in
  *backend*|*dashboard*) echo "Stop backend and dashboard before restoring"; exit 1 ;;
esac
"${production_compose[@]}" up -d --wait db
restore_tables="$("${production_compose[@]}" exec -T db psql -U app -d jobhunter -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
if [ "$restore_tables" != 0 ]; then echo "Refusing to restore into a non-empty database"; exit 1; fi
"${production_compose[@]}" run --rm -T --no-deps --entrypoint sh backend -c 'test -z "$(ls -A /app/storage)"' || { echo "Refusing to restore into a non-empty artifact volume"; exit 1; }
"${production_compose[@]}" run --rm -T --no-deps --entrypoint tar backend -xzf - --no-same-owner -C /app/storage < "$restore_source/artifacts.tar.gz"
"${production_compose[@]}" exec -T db pg_restore -U app -d jobhunter --no-owner --no-privileges --single-transaction --exit-on-error < "$restore_source/database.dump"
printf '%s\n' "Restore complete. Start backend/dashboard and verify readiness before reopening traffic."
