"""Phase 3 matching policy and requirement analyses"""

import sqlalchemy as sa
from alembic import op

revision = "89f14572321a"
down_revision = "9bafed112527"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_analyses",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=30), nullable=False),
        sa.Column("extractor_version", sa.String(length=50), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.add_column(
        "candidate_preferences",
        sa.Column("minimum_annual_salary", sa.Numeric(precision=14, scale=2), nullable=True),
    )
    op.add_column(
        "candidate_preferences", sa.Column("salary_currency", sa.String(length=3), nullable=True)
    )
    op.add_column(
        "candidate_preferences", sa.Column("open_to_relocation", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "candidate_preferences",
        sa.Column("work_authorized_countries", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column(
        "job_matches",
        sa.Column(
            "decision", sa.String(length=30), server_default="REVIEW_REQUIRED", nullable=False
        ),
    )
    op.add_column(
        "job_matches", sa.Column("threshold", sa.Integer(), server_default="80", nullable=False)
    )
    op.add_column("job_matches", sa.Column("profile_hash", sa.String(length=64), nullable=True))
    op.add_column("job_matches", sa.Column("job_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "job_matches", sa.Column("requirements_hash", sa.String(length=64), nullable=True)
    )
    op.add_column("job_matches", sa.Column("policy_version", sa.String(length=50), nullable=True))
    op.add_column("job_matches", sa.Column("as_of", sa.Date(), nullable=True))
    op.add_column("job_matches", sa.Column("execution_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_job_matches_decision"), "job_matches", ["decision"], unique=False)
    op.create_index(
        op.f("ix_job_matches_execution_id"), "job_matches", ["execution_id"], unique=False
    )
    op.create_foreign_key(
        "fk_match_execution", "job_matches", "agent_executions", ["execution_id"], ["id"]
    )

    op.create_check_constraint("ck_match_threshold", "job_matches", "threshold BETWEEN 0 AND 100")
    op.create_check_constraint(
        "ck_match_decision",
        "job_matches",
        "decision IN ('QUALIFIED','BELOW_THRESHOLD','NOT_QUALIFIED',"
        "'INELIGIBLE','REVIEW_REQUIRED')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_match_decision", "job_matches", type_="check")
    op.drop_constraint("ck_match_threshold", "job_matches", type_="check")
    op.drop_constraint("fk_match_execution", "job_matches", type_="foreignkey")
    op.drop_index(op.f("ix_job_matches_execution_id"), table_name="job_matches")
    op.drop_index(op.f("ix_job_matches_decision"), table_name="job_matches")
    op.drop_column("job_matches", "execution_id")
    op.drop_column("job_matches", "as_of")
    op.drop_column("job_matches", "policy_version")
    op.drop_column("job_matches", "requirements_hash")
    op.drop_column("job_matches", "job_hash")
    op.drop_column("job_matches", "profile_hash")
    op.drop_column("job_matches", "threshold")
    op.drop_column("job_matches", "decision")
    op.drop_column("candidate_preferences", "work_authorized_countries")
    op.drop_column("candidate_preferences", "open_to_relocation")
    op.drop_column("candidate_preferences", "salary_currency")
    op.drop_column("candidate_preferences", "minimum_annual_salary")
    op.drop_table("job_analyses")
