"""Preserve confirmed profile month and year precision"""

import sqlalchemy as sa
from alembic import op

revision = "9bafed112527"
down_revision = "3ac7cafc4071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("candidate_education", sa.Column("start_year", sa.Integer(), nullable=True))
    op.add_column(
        "candidate_experiences", sa.Column("start_month", sa.String(length=7), nullable=True)
    )
    op.add_column(
        "candidate_experiences", sa.Column("end_month", sa.String(length=7), nullable=True)
    )
    op.add_column("candidate_experiences", sa.Column("is_current", sa.Boolean(), nullable=True))

    op.create_check_constraint(
        "ck_education_year_order", "candidate_education", "graduation_year >= start_year"
    )
    op.create_check_constraint(
        "ck_experience_start_precision",
        "candidate_experiences",
        "start_date IS NULL OR start_month IS NULL",
    )
    op.create_check_constraint(
        "ck_experience_end_precision",
        "candidate_experiences",
        "end_date IS NULL OR end_month IS NULL",
    )
    op.create_check_constraint(
        "ck_experience_start_month",
        "candidate_experiences",
        "start_month IS NULL OR start_month ~ '^[1-9][0-9]{3}-(0[1-9]|1[0-2])$'",
    )
    op.create_check_constraint(
        "ck_experience_end_month",
        "candidate_experiences",
        "end_month IS NULL OR end_month ~ '^[1-9][0-9]{3}-(0[1-9]|1[0-2])$'",
    )
    op.create_check_constraint(
        "ck_experience_month_order",
        "candidate_experiences",
        "COALESCE(end_month, to_char(end_date, 'YYYY-MM')) >= "
        "COALESCE(start_month, to_char(start_date, 'YYYY-MM'))",
    )
    op.create_check_constraint(
        "ck_experience_current",
        "candidate_experiences",
        "is_current IS DISTINCT FROM TRUE OR (end_date IS NULL AND end_month IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_education_year_order", "candidate_education", type_="check")
    op.drop_constraint("ck_experience_current", "candidate_experiences", type_="check")
    op.drop_constraint("ck_experience_month_order", "candidate_experiences", type_="check")
    op.drop_constraint("ck_experience_end_month", "candidate_experiences", type_="check")
    op.drop_constraint("ck_experience_start_month", "candidate_experiences", type_="check")
    op.drop_constraint("ck_experience_end_precision", "candidate_experiences", type_="check")
    op.drop_constraint("ck_experience_start_precision", "candidate_experiences", type_="check")
    op.drop_column("candidate_experiences", "is_current")
    op.drop_column("candidate_experiences", "end_month")
    op.drop_column("candidate_experiences", "start_month")
    op.drop_column("candidate_education", "start_year")
