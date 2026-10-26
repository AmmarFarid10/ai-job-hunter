# Production operations

This runbook deploys the Phases 1–5 review product. It does not enable external application
submission. Use an isolated host/project for production; do not mix production and local volumes.

## Configure

1. Provide a domain pointing at a Linux host with Docker Compose and inbound ports 80/443.
   Only the gateway publishes ports. PostgreSQL, backend and dashboard stay on private networks.
2. Copy `.env.production.example` to `.env.production`, chmod it to 600, and replace every
   placeholder. Generate separate URL-safe secrets for POSTGRES_PASSWORD, API_KEY and GATEWAY_TOKEN.
   The database password is interpolated into a URL; generated URL-safe values avoid encoding errors.
3. Set APP_DOMAIN, DASHBOARD_URL, certificate contact and transactional SMTP credentials/sender.
   SMTP supports verified STARTTLS or SSL. Configure provider sender authorization, SPF/DKIM/DMARC
   and delivery monitoring with your provider. Do not use production recipients in automated tests.
4. Configure `discovery_sources.json` from its example. Fetch only authorized company boards and
   explicitly permitted pages. Add optional search/model credentials to the backend environment.
5. Optional Google sign-in must register exactly
   `https://YOUR_DOMAIN/api/oauth/google/callback`; no Gmail permissions are implied.
6. Keep REQUIRE_EMAIL_VERIFICATION=true, ALLOW_API_KEY_AUTH=false and ALLOW_ADMIN_BOOTSTRAP=false.
   Choose budgets appropriate to your provider subscription. Daily counters reset at UTC midnight;
   the global monthly discovery budget resets on the first UTC day of the month. A discovery run
   can make up to three requests per selected search provider; a budget is not an invoice estimate.
7. Choose a lawful retention policy, user privacy notice, support contact and administrator-access
   policy before accepting public resumes. These business/legal choices are operator responsibilities.

```sh
uv run python scripts/production_preflight.py .env.production
docker compose --env-file .env.production -f compose.production.yaml config --quiet
docker compose --env-file .env.production -f compose.production.yaml up -d --build --wait
```

Caddy obtains and renews HTTPS certificates. Its default forwarding behavior replaces untrusted
forwarded headers. Keep Caddy as the first public proxy; do not add a CDN or another proxy without
configuring and testing its trusted-proxy/IP policy. The dashboard adds the private gateway secret;
clients cannot use that header to grant themselves workspace permissions.

Initialize the administrator explicitly on the server:

```sh
docker compose --env-file .env.production -f compose.production.yaml exec backend .venv/bin/python -m app.admin
```

Then remove ADMIN_PASSWORD from the server environment file and recreate the backend. Passwords
are stored as salted hashes. Do not publish the populated file or print resolved Compose config.
Existing legacy data remains in the old owner's workspace or an administrator-only imported workspace.

## Launch gates

Do these against your actual deployment before making it public:

- Confirm HTTPS, expected hostname, Secure/HttpOnly cookies and redirect behavior.
- Sign up with a mailbox you control; verify the message arrives and the one-time link works.
  Business access must fail before verification. Exercise recovery and confirm old sessions fail.
- Complete Google consent if enabled. Mock JWT tests do not replace a real OAuth registration check.
- Check permissions using two accounts and administrator workspace selection.
- Confirm configured provider quotas, recent-date behavior and rate-limit messages.
- Create a private consistent backup and restore it on a separate empty deployment.
- Arrange off-site encryption, disk/capacity alerts, uptime monitoring, log retention, updates and
  an incident response contact. Tailor resource limits to measured traffic; no million-user claim
  or exhaustive security proof is made by this repository's test suite.

Authentication email runs after the HTTP response. Tokens are stored hashed, purpose-bound and
one-time. A process crash before delivery may lose a message; users can request a new link after
the cooldown. Delivery errors invalidate the issued token and record AUTH_MAIL_FAILED. Monitor
account security events and provider delivery dashboards; SMTP acceptance does not prove inbox arrival.

## Backup and restore

```sh
scripts/backup.sh /private/backups/new-snapshot
uv run python scripts/verify_backup.py /private/backups/new-snapshot
# On a separate, empty target deployment with backend/dashboard stopped:
RESTORE_CONFIRM_EMPTY=true scripts/restore.sh /private/backups/new-snapshot
```

Backup briefly stops writes, captures PostgreSQL and private artifacts together, creates SHA-256
checksums, then restarts services. The backup contains sensitive resumes and account data. Copy it
encrypted and off-site; checksums detect corruption but are not an authenticity signature against
an attacker who can replace the manifest. The restore script rejects non-empty targets and unsafe
artifact paths. It does not start public traffic. If restoration fails, keep the target offline,
discard only that empty restore target, and retry; never remove a live production volume.

## Monitor and update

`docker compose ... ps` reports health. Backend readiness checks schema version, database access
and storage write access. JSON logs include request IDs, status, duration and sanitized error types,
not request bodies, query strings or credentials. Docker log rotation limits local log growth.
Alert on failed readiness, rising 5xx/429 rates, AUTH_MAIL_FAILED, disk usage and uncertain notification
outcomes. Scheduled work and migrations use advisory locks across processes. Never blindly resend
an uncertain live notification.

Build new images, back up first, then deploy with `up -d --build --wait`. Schema changes use Alembic.
Workspace-isolation migrations deliberately block unsafe downgrade. Practice backup restoration
rather than assuming every schema change can be reversed. Pin image digests and re-run dependency
and container/host scans as part of your own release process.
