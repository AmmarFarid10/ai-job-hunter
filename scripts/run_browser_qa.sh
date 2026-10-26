#!/usr/bin/env bash
# Fictional-data browser QA on disposable PostgreSQL only. Never runs against live data.
set -euo pipefail
cd "$(dirname "$0")/.."
export TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql+asyncpg://test:test@localhost:55433/job_hunter_test}"
export DATABASE_URL="$TEST_DATABASE_URL"
export ENVIRONMENT=test API_KEY=browser-test-key-at-least-thirty-two-characters
export REQUIRE_EMAIL_VERIFICATION=false ALLOW_API_KEY_AUTH=true ALLOW_ADMIN_BOOTSTRAP=true
export SCHEDULER_ENABLED=false SMTP_HOST="" STORAGE_DIR=/tmp/job-hunter-browser-phase5
uv run python - <<'PY'
import asyncio,os,socket
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.models import Base
url=os.environ['TEST_DATABASE_URL']
if not url.rsplit('/',1)[-1].endswith('_test'):raise SystemExit('Refusing non-test database')
for port in (8001,3001):
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',port))==0:raise SystemExit('QA ports are already in use; no processes stopped')
async def reset():
    engine=create_async_engine(url)
    async with engine.begin() as connection:
        tables=','.join('"'+table.name+'"' for table in Base.metadata.sorted_tables)
        await connection.execute(text('TRUNCATE '+tables+' CASCADE'))
    await engine.dispose()
asyncio.run(reset())
PY
mkdir -p storage/qa_browser
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --no-access-log > storage/qa_browser/backend.log 2>&1 &
backend_pid=$!
(cd dashboard; exec env BACKEND_URL=http://127.0.0.1:8001 DASHBOARD_ORIGIN=http://localhost:3001 node node_modules/next/dist/bin/next start --port 3001 --hostname 127.0.0.1) > storage/qa_browser/dashboard.log 2>&1 &
dashboard_pid=$!
cleanup() { kill "$backend_pid" "$dashboard_pid" 2>/dev/null || true; wait "$backend_pid" "$dashboard_pid" 2>/dev/null || true; }
trap cleanup EXIT
uv run python - <<'PY'
import time,urllib.request
for port,path in ((8001,'/health/ready'),(3001,'/api/session')):
    for attempt in range(50):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}',timeout=1) as response:
                if response.status==200:break
        except OSError:time.sleep(0.2)
    else:raise SystemExit('QA service did not become ready; inspect private storage/qa_browser logs')
PY
node tests/browser_phase5.mjs
node tests/browser_workspaces.mjs
node tests/browser_account_ui.mjs
