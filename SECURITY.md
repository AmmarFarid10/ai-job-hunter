# Security

Do not post credentials, resumes, tokens, profile contents or database dumps in GitHub issues.
Report security findings privately to the repository owner through GitHub private vulnerability
reporting once enabled. No public email address or third-party reporting service is assumed.

Production uses verified-email sessions, private business workspaces and explicit administrator
scope. Operators can inspect user data; describe this access in the privacy notice for your service.
Maintenance API keys and web administrator bootstrap are disabled in production. Initialize an
administrator explicitly on the server. Keep `.env.production`, provider token files, database
and artifact backups out of Git. Rotate credentials if exposed and revoke affected sessions.

Dependencies are locked. CI runs application tests and frontend vulnerability auditing. Re-run
Python/runtime audits before deployment and after dependency changes; an audit is a point-in-time
check, not proof that a package has no vulnerabilities. Pin deployment image digests in your own
release process and apply host/database/image updates regularly.

LinkedIn pages are never scraped. Only configured providers and explicitly permitted career
pages may be fetched. Remote text is untrusted. No autonomous external applications are submitted.
