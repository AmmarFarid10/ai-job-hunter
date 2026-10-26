"""Private workspaces; preserve legacy records in a disabled administrator workspace.

Downgrade is deliberately blocked: collapsing multiple owners would expose private data.
"""

import hashlib
import uuid

import sqlalchemy as sa
from alembic import op

revision = "c8cab9d38fd5"
down_revision = "decaad941c05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_accounts",
        sa.Column("role", sa.String(10), nullable=False, server_default="USER"),
    )
    op.drop_constraint("ck_single_workspace_owner", "workspace_accounts", type_="check")
    op.drop_column("workspace_accounts", "slot")
    op.create_check_constraint("ck_account_role", "workspace_accounts", "role IN ('USER','ADMIN')")
    op.create_table(
        "admin_audit",
        sa.Column("actor_account_id", sa.Uuid(), nullable=False),
        sa.Column("target_account_id", sa.Uuid(), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("resource", sa.String(length=500), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"],
            ["workspace_accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_account_id"],
            ["workspace_accounts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("agent_executions", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("application_events", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("applications", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("approval_events", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("approval_requests", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("candidate_education", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("candidate_experiences", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("candidate_preferences", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("candidate_skills", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("candidates", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("discovery_items", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("job_analyses", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("job_identities", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("job_matches", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("job_requirements", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("job_sources", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("jobs", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column(
        "notification_deliveries", sa.Column("owner_account_id", sa.Uuid(), nullable=True)
    )
    op.add_column("notification_reports", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("notification_settings", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("resume_drafts", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.add_column("resume_versions", sa.Column("owner_account_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_agent_executions_owner_account_id"),
        "agent_executions",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_application_events_owner_account_id"),
        "application_events",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_applications_owner_account_id"), "applications", ["owner_account_id"], unique=False
    )
    op.create_index(
        op.f("ix_approval_events_owner_account_id"),
        "approval_events",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_approval_requests_owner_account_id"),
        "approval_requests",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_education_owner_account_id"),
        "candidate_education",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_experiences_owner_account_id"),
        "candidate_experiences",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_preferences_owner_account_id"),
        "candidate_preferences",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_skills_owner_account_id"),
        "candidate_skills",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidates_owner_account_id"), "candidates", ["owner_account_id"], unique=False
    )
    op.create_index(
        op.f("ix_discovery_items_owner_account_id"),
        "discovery_items",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_job_analyses_owner_account_id"), "job_analyses", ["owner_account_id"], unique=False
    )
    op.create_index(
        op.f("ix_job_identities_owner_account_id"),
        "job_identities",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_job_matches_owner_account_id"), "job_matches", ["owner_account_id"], unique=False
    )
    op.create_index(
        op.f("ix_job_requirements_owner_account_id"),
        "job_requirements",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_job_sources_owner_account_id"), "job_sources", ["owner_account_id"], unique=False
    )
    op.create_index(op.f("ix_jobs_owner_account_id"), "jobs", ["owner_account_id"], unique=False)
    op.create_index(
        op.f("ix_notification_deliveries_owner_account_id"),
        "notification_deliveries",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_reports_owner_account_id"),
        "notification_reports",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_settings_owner_account_id"),
        "notification_settings",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_drafts_owner_account_id"),
        "resume_drafts",
        ["owner_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_versions_owner_account_id"),
        "resume_versions",
        ["owner_account_id"],
        unique=False,
    )
    # Historical executions without replay keys receive independent, stable keys.
    op.execute(
        "UPDATE agent_executions SET idempotency_key='legacy:' || id::text "
        "WHERE idempotency_key IS NULL"
    )
    op.drop_constraint("uq_agent_execution_idempotency", "agent_executions", type_="unique")
    op.drop_constraint("uq_discovery_provider_external_id", "discovery_items", type_="unique")
    op.drop_constraint("applications_idempotency_key_key", "applications", type_="unique")
    op.create_unique_constraint(
        "uq_agent_execution_idempotency",
        "agent_executions",
        ["owner_account_id", "idempotency_key"],
        postgresql_nulls_not_distinct=True,
    )
    op.create_unique_constraint(
        "uq_owner_agent_executions", "agent_executions", ["owner_account_id", "id"]
    )
    op.create_unique_constraint(
        "uq_owner_application_events", "application_events", ["owner_account_id", "id"]
    )
    op.create_unique_constraint(
        "uq_application_replay",
        "applications",
        ["owner_account_id", "idempotency_key"],
        postgresql_nulls_not_distinct=True,
    )
    op.create_unique_constraint("uq_owner_applications", "applications", ["owner_account_id", "id"])
    op.create_unique_constraint(
        "uq_owner_approval_events", "approval_events", ["owner_account_id", "id"]
    )
    op.create_unique_constraint(
        "uq_owner_approval_requests", "approval_requests", ["owner_account_id", "id"]
    )
    op.create_unique_constraint(
        "uq_owner_candidate_education", "candidate_education", ["owner_account_id", "id"]
    )
    op.create_unique_constraint(
        "uq_owner_candidate_experiences", "candidate_experiences", ["owner_account_id", "id"]
    )
    op.create_unique_constraint(
        "uq_owner_candidate_preferences", "candidate_preferences", ["owner_account_id", "id"]
    )
    op.create_unique_constraint(
        "uq_owner_candidate_skills", "candidate_skills", ["owner_account_id", "id"]
    )
    op.create_unique_constraint("uq_owner_candidates", "candidates", ["owner_account_id", "id"])
    op.create_unique_constraint(
        "uq_discovery_provider_external_id",
        "discovery_items",
        ["owner_account_id", "provider", "external_id"],
        postgresql_nulls_not_distinct=True,
    )
    op.create_unique_constraint(
        "uq_owner_discovery_items", "discovery_items", ["owner_account_id", "id"]
    )
    op.create_unique_constraint("uq_owner_job_analyses", "job_analyses", ["owner_account_id", "id"])
    op.create_unique_constraint("uq_owner_job_matches", "job_matches", ["owner_account_id", "id"])
    op.create_unique_constraint(
        "uq_owner_job_requirements", "job_requirements", ["owner_account_id", "id"]
    )
    op.create_unique_constraint("uq_owner_job_sources", "job_sources", ["owner_account_id", "id"])
    op.create_unique_constraint("uq_owner_jobs", "jobs", ["owner_account_id", "id"])
    op.create_unique_constraint(
        "uq_owner_notification_deliveries", "notification_deliveries", ["owner_account_id", "id"]
    )
    op.create_unique_constraint(
        "uq_owner_notification_reports", "notification_reports", ["owner_account_id", "id"]
    )
    op.create_unique_constraint(
        "uq_owner_notification_settings", "notification_settings", ["owner_account_id", "id"]
    )
    op.create_unique_constraint(
        "uq_owner_resume_drafts", "resume_drafts", ["owner_account_id", "id"]
    )
    op.create_unique_constraint(
        "uq_owner_resume_versions", "resume_versions", ["owner_account_id", "id"]
    )
    connection = op.get_bind()
    owner = connection.scalar(sa.text("SELECT id FROM workspace_accounts LIMIT 1"))
    if owner is None:
        owner = uuid.uuid4()
        connection.execute(
            sa.text(
                "INSERT INTO workspace_accounts(id,name,email,password_hash,role) "
                "VALUES (:id,'Imported private workspace',:email,'!bootstrap','ADMIN')"
            ),
            {"id": owner, "email": f"{owner}@job-hunter.invalid"},
        )
    else:
        connection.execute(
            sa.text("UPDATE workspace_accounts SET role='ADMIN' WHERE id=:id"), {"id": owner}
        )
    # Immutable records may be changed only by this transactional migration.
    op.execute("ALTER TABLE resume_versions DISABLE TRIGGER immutable_resume_version")
    op.execute("ALTER TABLE approval_requests DISABLE TRIGGER immutable_approval_snapshot")
    for table in [
        "agent_executions",
        "application_events",
        "applications",
        "approval_events",
        "approval_requests",
        "candidate_education",
        "candidate_experiences",
        "candidate_preferences",
        "candidate_skills",
        "candidates",
        "discovery_items",
        "job_analyses",
        "job_identities",
        "job_matches",
        "job_requirements",
        "job_sources",
        "jobs",
        "notification_deliveries",
        "notification_reports",
        "notification_settings",
        "resume_drafts",
        "resume_versions",
    ]:
        connection.execute(
            sa.text(f'UPDATE "{table}" SET owner_account_id=:owner'), {"owner": owner}
        )
    identities = connection.execute(sa.text("SELECT key FROM job_identities")).scalars().all()
    for key in identities:
        connection.execute(
            sa.text("UPDATE job_identities SET key=:new WHERE key=:old"),
            {"new": hashlib.sha256(f"{owner}:{key}".encode()).hexdigest(), "old": key},
        )
    op.execute("ALTER TABLE resume_versions ENABLE TRIGGER immutable_resume_version")
    op.execute("ALTER TABLE approval_requests ENABLE TRIGGER immutable_approval_snapshot")
    op.create_foreign_key(
        None, "agent_executions", "workspace_accounts", ["owner_account_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_owner_application_events_application_id",
        "application_events",
        "applications",
        ["owner_account_id", "application_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        None, "application_events", "workspace_accounts", ["owner_account_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_owner_applications_approval_request_id",
        "applications",
        "approval_requests",
        ["owner_account_id", "approval_request_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        "fk_owner_applications_job_id",
        "applications",
        "jobs",
        ["owner_account_id", "job_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(None, "applications", "workspace_accounts", ["owner_account_id"], ["id"])
    op.create_foreign_key(
        "fk_owner_applications_candidate_id",
        "applications",
        "candidates",
        ["owner_account_id", "candidate_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        None, "approval_events", "workspace_accounts", ["owner_account_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_owner_approval_events_approval_id",
        "approval_events",
        "approval_requests",
        ["owner_account_id", "approval_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        "fk_owner_approval_requests_candidate_id",
        "approval_requests",
        "candidates",
        ["owner_account_id", "candidate_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        "fk_owner_approval_requests_resume_version_id",
        "approval_requests",
        "resume_versions",
        ["owner_account_id", "resume_version_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        None, "approval_requests", "workspace_accounts", ["owner_account_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_owner_approval_requests_job_id",
        "approval_requests",
        "jobs",
        ["owner_account_id", "job_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        None, "candidate_education", "workspace_accounts", ["owner_account_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_owner_candidate_education_candidate_id",
        "candidate_education",
        "candidates",
        ["owner_account_id", "candidate_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        "fk_owner_candidate_experiences_candidate_id",
        "candidate_experiences",
        "candidates",
        ["owner_account_id", "candidate_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        None, "candidate_experiences", "workspace_accounts", ["owner_account_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_owner_candidate_preferences_candidate_id",
        "candidate_preferences",
        "candidates",
        ["owner_account_id", "candidate_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        None, "candidate_preferences", "workspace_accounts", ["owner_account_id"], ["id"]
    )
    op.create_foreign_key(
        None, "candidate_skills", "workspace_accounts", ["owner_account_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_owner_candidate_skills_candidate_id",
        "candidate_skills",
        "candidates",
        ["owner_account_id", "candidate_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(None, "candidates", "workspace_accounts", ["owner_account_id"], ["id"])
    op.create_foreign_key(
        "fk_owner_discovery_items_job_id",
        "discovery_items",
        "jobs",
        ["owner_account_id", "job_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        None, "discovery_items", "workspace_accounts", ["owner_account_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_owner_discovery_items_execution_id",
        "discovery_items",
        "agent_executions",
        ["owner_account_id", "execution_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        "fk_owner_job_analyses_job_id",
        "job_analyses",
        "jobs",
        ["owner_account_id", "job_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(None, "job_analyses", "workspace_accounts", ["owner_account_id"], ["id"])
    op.create_foreign_key(
        "fk_owner_job_identities_job_id",
        "job_identities",
        "jobs",
        ["owner_account_id", "job_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        None, "job_identities", "workspace_accounts", ["owner_account_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_owner_job_matches_candidate_id",
        "job_matches",
        "candidates",
        ["owner_account_id", "candidate_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(None, "job_matches", "workspace_accounts", ["owner_account_id"], ["id"])
    op.create_foreign_key(
        "fk_owner_job_matches_execution_id",
        "job_matches",
        "agent_executions",
        ["owner_account_id", "execution_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        "fk_owner_job_matches_job_id",
        "job_matches",
        "jobs",
        ["owner_account_id", "job_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        None, "job_requirements", "workspace_accounts", ["owner_account_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_owner_job_requirements_job_id",
        "job_requirements",
        "jobs",
        ["owner_account_id", "job_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        "fk_owner_job_sources_job_id",
        "job_sources",
        "jobs",
        ["owner_account_id", "job_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(None, "job_sources", "workspace_accounts", ["owner_account_id"], ["id"])
    op.create_foreign_key(None, "jobs", "workspace_accounts", ["owner_account_id"], ["id"])
    op.create_foreign_key(
        "fk_owner_notification_deliveries_report_id",
        "notification_deliveries",
        "notification_reports",
        ["owner_account_id", "report_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        None, "notification_deliveries", "workspace_accounts", ["owner_account_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_owner_notification_deliveries_job_id",
        "notification_deliveries",
        "jobs",
        ["owner_account_id", "job_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        "fk_owner_notification_deliveries_candidate_id",
        "notification_deliveries",
        "candidates",
        ["owner_account_id", "candidate_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        None, "notification_reports", "workspace_accounts", ["owner_account_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_owner_notification_reports_candidate_id",
        "notification_reports",
        "candidates",
        ["owner_account_id", "candidate_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        "fk_owner_notification_settings_candidate_id",
        "notification_settings",
        "candidates",
        ["owner_account_id", "candidate_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        None, "notification_settings", "workspace_accounts", ["owner_account_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_owner_resume_drafts_candidate_id",
        "resume_drafts",
        "candidates",
        ["owner_account_id", "candidate_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(None, "resume_drafts", "workspace_accounts", ["owner_account_id"], ["id"])
    op.create_foreign_key(
        "fk_owner_resume_versions_job_id",
        "resume_versions",
        "jobs",
        ["owner_account_id", "job_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        None, "resume_versions", "workspace_accounts", ["owner_account_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_owner_resume_versions_execution_id",
        "resume_versions",
        "agent_executions",
        ["owner_account_id", "execution_id"],
        ["owner_account_id", "id"],
    )
    op.create_foreign_key(
        "fk_owner_resume_versions_candidate_id",
        "resume_versions",
        "candidates",
        ["owner_account_id", "candidate_id"],
        ["owner_account_id", "id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Workspace isolation cannot be removed safely; restore a pre-migration backup instead"
    )
