"""Global discovery budget prevents unbounded provider spend across public accounts."""

import sqlalchemy as sa
from alembic import op

revision = "d932a0420bb6"
down_revision = "a7f924a1b209"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "global_usage_counters",
        sa.Column("action", sa.String(30), primary_key=True),
        sa.Column("bucket", sa.Date(), primary_key=True),
        sa.Column("used", sa.Integer(), nullable=False),
        sa.CheckConstraint("used >= 0", name="ck_global_usage_nonnegative"),
    )


def downgrade() -> None:
    op.drop_table("global_usage_counters")
