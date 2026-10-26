"""Phase 2 discovery observations and idempotent executions"""

import sqlalchemy as sa
from alembic import op

revision = "3ac7cafc4071"
down_revision = "8809e6755741"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_items",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("external_id", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('REVIEW_REQUIRED', 'IMPORTED', 'CONFLICT', 'DISMISSED')",
            name="ck_discovery_item_status",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["agent_executions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "external_id", name="uq_discovery_provider_external_id"),
    )
    op.create_index(
        op.f("ix_discovery_items_execution_id"), "discovery_items", ["execution_id"], unique=False
    )
    op.create_index(op.f("ix_discovery_items_job_id"), "discovery_items", ["job_id"], unique=False)
    op.create_index(
        op.f("ix_discovery_items_provider"), "discovery_items", ["provider"], unique=False
    )
    op.create_index(op.f("ix_discovery_items_status"), "discovery_items", ["status"], unique=False)
    op.add_column(
        "agent_executions", sa.Column("idempotency_key", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "agent_executions", sa.Column("request_hash", sa.String(length=64), nullable=True)
    )
    op.create_unique_constraint(
        "uq_agent_execution_idempotency", "agent_executions", ["idempotency_key"]
    )
    op.add_column("jobs", sa.Column("application_instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "application_instructions")
    op.drop_constraint("uq_agent_execution_idempotency", "agent_executions", type_="unique")
    op.drop_column("agent_executions", "request_hash")
    op.drop_column("agent_executions", "idempotency_key")
    op.drop_index(op.f("ix_discovery_items_status"), table_name="discovery_items")
    op.drop_index(op.f("ix_discovery_items_provider"), table_name="discovery_items")
    op.drop_index(op.f("ix_discovery_items_job_id"), table_name="discovery_items")
    op.drop_index(op.f("ix_discovery_items_execution_id"), table_name="discovery_items")
    op.drop_table("discovery_items")
