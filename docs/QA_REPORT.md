# Release QA report

Validated 2026-10-26. Scope: Phases 1–5, with external job application submission disabled.
These results cover the scenarios below; they do not establish that every possible edge case or
production traffic pattern has been tested.

## Results

| Check | Result |
| --- | --- |
| `uv run ruff check .` and format check | Pass |
| `uv run mypy app` | Pass; 80 source files |
| PostgreSQL regression suite | 238 passed on host; 238 passed again inside the Docker test image |
| Empty PostgreSQL database: all Alembic upgrades and schema comparison | Pass; no schema drift |
| Frontend unit/security tests | 7 passed |
| Next.js production build and TypeScript checks | Pass |
| Backend and dashboard release Docker builds | Pass; runtime containers use non-root users |
| Updated local deployment | Healthy; administrator login, imported workspace, existing resumes/jobs and audit smoke checks passed |
| Browser workflows | Three workflows passed, desktop and mobile checks included |
| Python runtime dependency audit | No known vulnerabilities reported at scan time |
| Frontend production dependency audit | No known vulnerabilities reported at scan time |
| Production Compose template and configuration preflight | Pass with fictional configuration |
| Caddy configuration validation | Pass, offline validation only |
| Configured company jobs API | Read-only HTTPS request passed with pinned public IP and TLS hostname verification |
| Backup restoration | Fictional PostgreSQL data restored to an empty database; selected record counts matched; all 12 artifact files matched SHA-256 |
| Source release privacy scan | Pass; populated environments, resumes, artifacts and private history excluded |

## Scenarios reviewed

- Password and Google authentication boundaries, inactive/Google-only accounts, malformed inputs,
  duplicate signup races, session expiry/revocation and administrator initialization restrictions.
- Verification and password-reset expiry, purpose separation, single use, parallel redemption,
  cooldowns, SMTP failures, TLS transport, hashed tokens and reset revocation of existing sessions.
- Separate user workspaces, denied cross-user access, administrator selection and audit records.
- Unverified-email business access denial, production gateway checks, disabled maintenance-key
  access and rejection of unsafe production settings.
- Concurrent usage reservations, global daily/monthly discovery limits, candidate caps, bounded
  pagination/request bodies, replay behavior and discovery execution persistence.
- Recent posting evidence, missing/old/future dates, configured-source restrictions, redirects,
  private addresses, DNS rebinding protection and aggregate discovery item limits.
- Distinct vacancies with similar text, exact identifier deduplication and database uniqueness.
- Resume upload/explicit confirmation, extraction evidence, overlapping experience, eligibility
  unknowns, deterministic matching and tailoring restricted to verified facts.
- Immutable artifact bytes, hash-checked downloads, expired/revoked approvals and state changes.
- Markdown formatting and unsafe HTML/URL/image rejection, CSRF/origin checks, proxy traversal,
  recovery fragment removal, same-page link navigation, password confirmation and mobile layout.
- Backup corruption, unsafe archive paths/links and exclusion of private files from source exports.

The review corrected same-page recovery-link handling, content-only vacancy merging, missing
company posting-date checks, production access/configuration gaps and missing resource budgets.
The final regression runs passed after those corrections. Five PyMuPDF/SWIG deprecation warnings
remain in the backend test output; they did not fail the run.

## Reproduce

Follow README.md for the disposable database and normal checks. Run
`scripts/run_browser_qa.sh` after building the dashboard. Test database names must end in `_test`;
the fixtures deliberately truncate their tables. Browser tests use fictional data and isolated
ports 8001/3001. Authentication UI tests mock mail-action responses; token semantics and races are
separately tested against PostgreSQL. SMTP transport tests do not send real email.

## Remaining deployment checks

Actual public DNS/TLS, sender authorization/inbox delivery, Google consent configuration, off-site
backup access, operator alerts, host/container scans and realistic load tests require the target
hosting environment. Complete the launch gates in PRODUCTION.md before public registration.
The included Compose resources are a starting capacity configuration, not a million-user benchmark.
Dependency results are time-specific and do not cover every operating-system package.
GitHub CI is configured but has not run remotely; this work does not publish a repository.
Production email uses background delivery with documented resend/crash behavior, not a durable queue.
External application submission remains disabled as required by the project scope.
