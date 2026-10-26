# Architecture

FastAPI serves typed business APIs. PostgreSQL stores accounts, private workspaces, canonical
jobs, discovery observations, deterministic matches, immutable resume versions and exact-version
approval records. Next.js provides the dashboard and same-origin server gateway. Private artifacts
live in a separate persistent volume and are never publicly served.

LangGraph orchestrates three bounded workflows in `app/agents/`: discovery, matching and resume
tailoring. Python services implement policy. Matching defaults to deterministic rules; optional
model extraction only returns evidence-checked requirements. Candidate facts require explicit
confirmation. Tailoring cannot add claims. Approval does not trigger external submission.

Workspace scope is assigned from the authenticated account on every request. ORM criteria apply
to reads and bulk writes; new records inherit ownership. Composite foreign keys reject cross-owner
references, and ownership is immutable in PostgreSQL. Raw maintenance queries are trusted server
operations, not exposed user capabilities. Administrator workspace selection is explicit and audited.

Production architecture: Internet → Caddy HTTPS → Next.js gateway → FastAPI → PostgreSQL/private
artifact volume. Only Caddy publishes ports. The gateway adds a private shared header; browser
headers cannot authorize backend access. Password/Google authentication have persisted throttles.
Unverified accounts can manage authentication but cannot access business records. Recovery links
are purpose-bound, hashed, expiring and consumed once under account locks. Reset revokes all
sessions; SMTP is TLS-verified and runs after the response. Lost delivery requires requesting a
new link; authentication mail is not a durable general-purpose queue.

Per-user UTC-day counters and global discovery budgets are PostgreSQL-atomic. Failed costly work
consumes budget; valid idempotent discovery/matching/generation replays do not. Configured source
selection never authorizes arbitrary URL crawling. Recent searches exclude unknown/future/old
posting dates and never equate update/crawl timestamps with posting dates.

Migrations and scheduled reports each use distributed advisory locks. Scheduled workers retain
workspace ownership and skip unverified accounts when verification is required. Notification outbox
states prevent blind retries after uncertain provider outcomes. All application submission paths
remain disabled under the repository's Phases 1–5 scope.

See `docs/PRODUCTION.md` for operations and `docs/QA_REPORT.md` for tested behavior and limits.
