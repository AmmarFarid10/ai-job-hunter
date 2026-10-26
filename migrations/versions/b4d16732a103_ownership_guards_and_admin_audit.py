"""Immutable ownership and append-only administrator access history."""

from alembic import op

revision = "b4d16732a103"
down_revision = "c8cab9d38fd5"
branch_labels = None
depends_on = None

TABLES = (
    "candidates",
    "candidate_skills",
    "candidate_experiences",
    "candidate_education",
    "candidate_preferences",
    "resume_drafts",
    "jobs",
    "job_identities",
    "job_sources",
    "job_requirements",
    "job_matches",
    "resume_versions",
    "approval_requests",
    "applications",
    "application_events",
    "notification_deliveries",
    "agent_executions",
    "discovery_items",
    "job_analyses",
    "approval_events",
    "notification_settings",
    "notification_reports",
)


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION prevent_owner_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.owner_account_id IS DISTINCT FROM OLD.owner_account_id THEN
                RAISE EXCEPTION 'Workspace ownership is immutable';
            END IF;
            RETURN NEW;
        END $$
    """)
    for table in TABLES:
        op.execute(
            f'CREATE TRIGGER immutable_owner BEFORE UPDATE ON "{table}" '
            "FOR EACH ROW EXECUTE FUNCTION prevent_owner_change()"
        )
    op.execute("""
        CREATE FUNCTION prevent_admin_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Administrator audit records are immutable'; END $$
    """)
    op.execute(
        "CREATE TRIGGER immutable_admin_audit BEFORE UPDATE OR DELETE ON admin_audit "
        "FOR EACH ROW EXECUTE FUNCTION prevent_admin_audit_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER immutable_admin_audit ON admin_audit")
    op.execute("DROP FUNCTION prevent_admin_audit_mutation()")
    for table in TABLES:
        op.execute(f'DROP TRIGGER immutable_owner ON "{table}"')
    op.execute("DROP FUNCTION prevent_owner_change()")
