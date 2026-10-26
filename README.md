# AI Job Hunter

A Python/FastAPI and Next.js application for discovering jobs, reviewing verified resume facts,
matching requirements, generating immutable resume drafts and recording exact-version approvals.
LangGraph orchestrates the discovery, matching and tailoring workflows.

**Scope: Phases 1–5. External application submission is disabled.** Approval is a review record,
not evidence that an employer received an application. This is not a general web crawler.

## Features

- Password and optional Google sign-in, email verification and one-time password recovery.
- Private per-user workspaces with explicit administrator access and audit history.
- PDF master-resume upload, extracted suggestions and explicit fact confirmation.
- Unified search across configured Greenhouse/Lever/company sources and indexed LinkedIn leads.
- Seven-day posting evidence for recent searches; unknown dates are excluded, not invented.
- Exact vacancy deduplication; similar text alone never merges separate vacancies.
- Deterministic requirement matching, optional evidence-checked AI extraction and resume tailoring.
- Private immutable PDF/DOCX artifacts, hash-checked downloads and precise approval/revocation.
- Persisted per-user limits, global provider budgets, TLS gateway and deployment/backup tooling.

## Local development

Requirements: Docker Compose, Python 3.12 with `uv`, and Node 22 for local frontend development.

```sh
cp .env.example .env
# Replace API_KEY with a generated private value; configure optional providers as needed.
cp discovery_sources.example.json discovery_sources.json
# Start with the optional source-config mount:
docker compose -f compose.yaml -f compose.discovery.yaml up -d --build
```

Open http://localhost:3000. Create a regular account. Development does not require email
verification by default. To initialize an administrator explicitly, set ADMIN_EMAIL and
ADMIN_PASSWORD in the backend `.env`, recreate the backend, then run:

```sh
docker compose exec backend .venv/bin/python -m app.admin
```

Initialization never silently resets an existing account password. Set up SMTP before testing
real verification/recovery mail; development without SMTP does not deliver email. Public production
requires SMTP and email verification. Google sign-in needs a Web OAuth client and the exact
registered callback `/api/oauth/google/callback`; only openid/email/profile scopes are requested.

Use **Job search → All configured sources** to search supported company boards and LinkedIn
search providers together. Company APIs must supply a posting date (`first_published`, `createdAt`
or structured `datePosted`); an updated timestamp is insufficient. Some sources will therefore
have fewer or no recent results. The original source always needs human review. Source links
are labeled as LinkedIn job listings, hiring posts or company/career pages. LinkedIn itself is
never fetched. Hiring posts may describe multiple vacancies and remain separate review leads.

Ordinary business APIs require `X-Owner-Session`. The development maintenance `X-API-Key`
bypasses user isolation and must stay private; it is disabled in production. Trusted local
maintenance scripts can explicitly select an owner with `X-Workspace-User`. Server Gmail tokens
are restricted to administrators and are unrelated to Google sign-in scopes.

## Production deployment

Use the separate [production runbook](docs/PRODUCTION.md), not development Compose. The production
stack exposes only the HTTPS gateway. It refuses unsafe configuration, requires verified email,
and disables maintenance-key access and web administrator bootstrap.

Before opening public traffic, configure a domain, real transactional SMTP, private secrets,
backups and your own privacy/retention/support policies. Run the documented DNS/TLS and email
smoke checks. External provider setup cannot be verified merely by passing local tests.

## Verification

Integration tests intentionally truncate only disposable databases whose names end in `_test`.
Never point TEST_DATABASE_URL at your live database.

```sh
uv sync --frozen --extra dev
docker compose --profile test up -d test-db
DATABASE_URL=postgresql+asyncpg://test:test@localhost:55433/job_hunter_test uv run alembic upgrade head
uv run ruff check .
uv run mypy app
TEST_DATABASE_URL=postgresql+asyncpg://test:test@localhost:55433/job_hunter_test uv run pytest -q
npm --prefix dashboard ci
npm --prefix dashboard test
npm --prefix dashboard run build
```

See [QA report](docs/QA_REPORT.md) for exact checks, results and limits. Browser verification
uses fictional data on isolated ports. `scripts/run_browser_qa.sh` starts those services and runs
the browser workflows against a disposable test database; it never submits applications.

## Prepare for GitHub

```sh
uv run python scripts/release_bundle.py --check
uv run python scripts/release_bundle.py
```

Upload the contents of `dist/ai-job-hunter-source.zip` to your repository. The source-only archive
excludes populated environment files, resumes, generated artifacts, private development history,
backups, caches and installed dependencies. It checks recognizable credentials and actual private
values from local environment files without printing those values. Review the archive yourself
before publishing. CI runs checks after you upload; no remote CI run is implied by local results.

Read [architecture](ARCHITECTURE.md) and [security guidance](SECURITY.md) before operating the app.
