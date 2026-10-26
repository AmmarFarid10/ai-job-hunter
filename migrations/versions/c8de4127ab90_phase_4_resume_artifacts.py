"""Phase 4 immutable resume documents and artifact manifests."""

import sqlalchemy as sa
from alembic import op

revision = "c8de4127ab90"
down_revision = "89f14572321a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, type_ in [
        ("pdf_storage_key", sa.Text()),
        ("docx_sha256", sa.String(64)),
        ("pdf_sha256", sa.String(64)),
        ("document_data", sa.JSON()),
        ("profile_hash", sa.String(64)),
        ("job_hash", sa.String(64)),
        ("requirements_hash", sa.String(64)),
        ("tailoring_version", sa.String(50)),
        ("execution_id", sa.Uuid()),
    ]:
        op.add_column("resume_versions", sa.Column(name, type_, nullable=True))
    op.add_column(
        "resume_versions",
        sa.Column("generation_mode", sa.String(20), nullable=False, server_default="qualified"),
    )
    op.add_column(
        "resume_versions",
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
    )
    op.create_foreign_key(
        "fk_resume_execution", "resume_versions", "agent_executions", ["execution_id"], ["id"]
    )
    op.create_index("ix_resume_versions_execution_id", "resume_versions", ["execution_id"])
    op.create_check_constraint("ck_resume_version_positive", "resume_versions", "version > 0")
    op.create_check_constraint(
        "ck_resume_generation_mode", "resume_versions", "generation_mode IN ('qualified','review')"
    )
    op.create_check_constraint(
        "ck_resume_draft_status", "resume_versions", "status IN ('DRAFT','DRAFT_REVIEW')"
    )
    op.execute("""CREATE FUNCTION prevent_resume_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Resume versions are immutable' USING ERRCODE = '23514'; END $$""")
    op.execute(
        "CREATE TRIGGER immutable_resume_version BEFORE UPDATE OR DELETE ON resume_versions "
        "FOR EACH ROW EXECUTE FUNCTION prevent_resume_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER immutable_resume_version ON resume_versions")
    op.execute("DROP FUNCTION prevent_resume_mutation()")
    for name in [
        "ck_resume_draft_status",
        "ck_resume_generation_mode",
        "ck_resume_version_positive",
    ]:
        op.drop_constraint(name, "resume_versions", type_="check")
    op.drop_index("ix_resume_versions_execution_id", "resume_versions")
    op.drop_constraint("fk_resume_execution", "resume_versions", type_="foreignkey")
    for name in [
        "status",
        "generation_mode",
        "execution_id",
        "tailoring_version",
        "requirements_hash",
        "job_hash",
        "profile_hash",
        "document_data",
        "pdf_sha256",
        "docx_sha256",
        "pdf_storage_key",
    ]:
        op.drop_column("resume_versions", name)
