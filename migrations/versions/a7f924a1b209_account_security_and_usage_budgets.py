"""Email verification, one-time account recovery and persisted resource budgets."""

import sqlalchemy as sa
from alembic import op

revision = "a7f924a1b209"
down_revision = "b4d16732a103"
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.add_column("workspace_accounts", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    # Only identities proven by Google-only signup or explicitly provisioned admins are trusted.
    op.execute(
        "UPDATE workspace_accounts SET email_verified_at=now() WHERE "
        "(role='ADMIN' AND password_hash != '!bootstrap') OR password_hash='!google-only'"
    )
    op.create_table(
        "account_action_tokens",
        *timestamps(),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("workspace_accounts.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("purpose", sa.String(10), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("purpose IN ('verify','reset')", name="ck_account_token_purpose"),
    )
    op.create_index("ix_account_action_tokens_account_id", "account_action_tokens", ["account_id"])
    op.create_table(
        "account_security_events",
        *timestamps(),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("workspace_accounts.id"), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
    )
    op.create_index(
        "ix_account_security_events_account_id", "account_security_events", ["account_id"]
    )
    op.create_table(
        "usage_counters",
        sa.Column(
            "account_id", sa.Uuid(), sa.ForeignKey("workspace_accounts.id"), primary_key=True
        ),
        sa.Column("action", sa.String(30), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("used", sa.Integer(), nullable=False),
        sa.CheckConstraint("used >= 0", name="ck_usage_nonnegative"),
    )


def downgrade() -> None:
    op.drop_table("usage_counters")
    op.drop_table("account_security_events")
    op.drop_table("account_action_tokens")
    op.drop_column("workspace_accounts", "email_verified_at")
