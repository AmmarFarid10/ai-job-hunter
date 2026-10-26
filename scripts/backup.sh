#!/usr/bin/env bash
# Consistent database + artifact backup, with a brief write outage. Run on the production host.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
backup_target="${1:?Usage: scripts/backup.sh /private/path/to/new-backup-directory}"
if [ -e "$backup_target" ]; then echo "Refusing to overwrite an existing backup directory"; exit 1; fi
mkdir -m 700 -p "$backup_target"
backup_target="$(cd "$backup_target" && pwd)"
production_compose=(docker compose --env-file .env.production -f compose.production.yaml)
restart_services() { "${production_compose[@]}" up -d backend dashboard >/dev/null; }
trap restart_services EXIT
"${production_compose[@]}" stop dashboard backend
"${production_compose[@]}" exec -T db pg_dump -U app -d jobhunter -Fc > "$backup_target/database.dump"
"${production_compose[@]}" run --rm --no-deps --entrypoint tar backend -czf - -C /app/storage . > "$backup_target/artifacts.tar.gz"
python3 - "$backup_target" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])
def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()
manifest={name:digest(root/name) for name in ('database.dump','artifacts.tar.gz')}
(root/'manifest.json').write_text(json.dumps(manifest,indent=2))
PY
printf '%s\n' "Backup complete. Store this private directory encrypted and off-site."
