import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.states import State


class Base(DeclarativeBase):
    # Fetch server timestamps during flush, avoiding implicit async lazy loads.
    __mapper_args__ = {"eager_defaults": True}


class Owned:
    owner_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspace_accounts.id"), index=True
    )


class Record:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Candidate(Owned, Record, Base):
    __tablename__ = "candidates"
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    location: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


class CandidateSkill(Owned, Record, Base):
    __tablename__ = "candidate_skills"
    __table_args__ = (UniqueConstraint("candidate_id", "normalized_name"),)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200))
    verified: Mapped[bool] = mapped_column(default=False)


class CandidateExperience(Owned, Record, Base):
    __tablename__ = "candidate_experiences"
    __table_args__ = (
        CheckConstraint("end_date IS NULL OR end_date >= start_date"),
        CheckConstraint(
            "start_date IS NULL OR start_month IS NULL", name="ck_experience_start_precision"
        ),
        CheckConstraint(
            "end_date IS NULL OR end_month IS NULL", name="ck_experience_end_precision"
        ),
        CheckConstraint(
            "start_month IS NULL OR start_month ~ '^[1-9][0-9]{3}-(0[1-9]|1[0-2])$'",
            name="ck_experience_start_month",
        ),
        CheckConstraint(
            "end_month IS NULL OR end_month ~ '^[1-9][0-9]{3}-(0[1-9]|1[0-2])$'",
            name="ck_experience_end_month",
        ),
        CheckConstraint(
            "COALESCE(end_month, to_char(end_date, 'YYYY-MM')) >= "
            "COALESCE(start_month, to_char(start_date, 'YYYY-MM'))",
            name="ck_experience_month_order",
        ),
        CheckConstraint(
            "is_current IS DISTINCT FROM TRUE OR (end_date IS NULL AND end_month IS NULL)",
            name="ck_experience_current",
        ),
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id"), index=True)
    employer: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    start_month: Mapped[str | None] = mapped_column(String(7))
    end_month: Mapped[str | None] = mapped_column(String(7))
    is_current: Mapped[bool | None] = mapped_column(Boolean)
    bullets: Mapped[list[str]] = mapped_column(JSON, default=list)
    verified: Mapped[bool] = mapped_column(default=False)


class CandidateEducation(Owned, Record, Base):
    __tablename__ = "candidate_education"
    __table_args__ = (
        CheckConstraint("graduation_year >= start_year", name="ck_education_year_order"),
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id"), index=True)
    institution: Mapped[str] = mapped_column(String(200))
    degree: Mapped[str] = mapped_column(String(200))
    graduation_year: Mapped[int | None] = mapped_column(Integer)
    start_year: Mapped[int | None] = mapped_column(Integer)
    verified: Mapped[bool] = mapped_column(default=False)


class CandidatePreference(Owned, Record, Base):
    __tablename__ = "candidate_preferences"
    __table_args__ = (CheckConstraint("match_threshold BETWEEN 0 AND 100"),)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id"), unique=True)
    match_threshold: Mapped[int] = mapped_column(default=80)
    roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    remote_pakistan_priority: Mapped[bool] = mapped_column(default=True)
    minimum_annual_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    open_to_relocation: Mapped[bool | None] = mapped_column(Boolean)
    work_authorized_countries: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )


class ResumeDraft(Owned, Record, Base):
    __tablename__ = "resume_drafts"
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64))
    extracted_text: Mapped[str] = mapped_column(Text)
    suggestions: Mapped[dict[str, Any]] = mapped_column(JSON)
    warnings: Mapped[list[str]] = mapped_column(JSON)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_profile: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class Job(Owned, Record, Base):
    __tablename__ = "jobs"
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(300))
    normalized_title: Mapped[str] = mapped_column(String(300), index=True)
    normalized_company: Mapped[str] = mapped_column(String(300), index=True)
    description: Mapped[str] = mapped_column(Text)
    description_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    application_url: Mapped[str | None] = mapped_column(Text)
    application_instructions: Mapped[str | None] = mapped_column(Text)
    employer_job_id: Mapped[str | None] = mapped_column(String(200))
    linkedin_job_id: Mapped[str | None] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(300))
    work_authorization: Mapped[str | None] = mapped_column(Text)
    geographic_restrictions: Mapped[str | None] = mapped_column(Text)
    pakistan_eligible: Mapped[bool | None] = mapped_column(Boolean)
    relocation_support: Mapped[bool | None] = mapped_column(Boolean)
    sponsorship: Mapped[bool | None] = mapped_column(Boolean)
    compensation: Mapped[str | None] = mapped_column(String(500))


class JobIdentity(Owned, Base):
    __tablename__ = "job_identities"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), index=True)


class JobSource(Owned, Record, Base):
    __tablename__ = "job_sources"
    __table_args__ = (UniqueConstraint("job_id", "canonical_url"),)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    provider: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)


class JobRequirement(Owned, Record, Base):
    __tablename__ = "job_requirements"
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    category: Mapped[str] = mapped_column(String(100))
    value: Mapped[str] = mapped_column(Text)
    required: Mapped[bool] = mapped_column(default=True)


class JobMatch(Owned, Record, Base):
    __tablename__ = "job_matches"
    __table_args__ = (
        UniqueConstraint("candidate_id", "job_id"),
        CheckConstraint("score BETWEEN 0 AND 100"),
        CheckConstraint("threshold BETWEEN 0 AND 100", name="ck_match_threshold"),
        CheckConstraint(
            "decision IN ('QUALIFIED','BELOW_THRESHOLD','NOT_QUALIFIED',"
            "'INELIGIBLE','REVIEW_REQUIRED')",
            name="ck_match_decision",
        ),
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"))
    score: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(30), server_default="REVIEW_REQUIRED", index=True)
    threshold: Mapped[int] = mapped_column(Integer, server_default="80")
    profile_hash: Mapped[str | None] = mapped_column(String(64))
    job_hash: Mapped[str | None] = mapped_column(String(64))
    requirements_hash: Mapped[str | None] = mapped_column(String(64))
    policy_version: Mapped[str | None] = mapped_column(String(50))
    as_of: Mapped[date | None] = mapped_column(Date)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_executions.id", name="fk_match_execution"), index=True
    )
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ResumeVersion(Owned, Record, Base):
    __tablename__ = "resume_versions"
    __table_args__ = (
        UniqueConstraint("candidate_id", "job_id", "version"),
        CheckConstraint("version > 0", name="ck_resume_version_positive"),
        CheckConstraint(
            "generation_mode IN ('qualified','review')", name="ck_resume_generation_mode"
        ),
        CheckConstraint("status IN ('DRAFT','DRAFT_REVIEW')", name="ck_resume_draft_status"),
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"))
    version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(Text)
    pdf_storage_key: Mapped[str | None] = mapped_column(Text)
    docx_sha256: Mapped[str | None] = mapped_column(String(64))
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    document_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    profile_hash: Mapped[str | None] = mapped_column(String(64))
    job_hash: Mapped[str | None] = mapped_column(String(64))
    requirements_hash: Mapped[str | None] = mapped_column(String(64))
    tailoring_version: Mapped[str | None] = mapped_column(String(50))
    generation_mode: Mapped[str] = mapped_column(String(20), server_default="qualified")
    status: Mapped[str] = mapped_column(String(30), server_default="DRAFT")
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_executions.id", name="fk_resume_execution"), index=True
    )


class ApprovalRequest(Owned, Record, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','CHANGES_REQUESTED','REVOKED')",
            name="ck_approval_status",
        ),
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"))
    resume_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resume_versions.id"))
    resume_hash: Mapped[str] = mapped_column(String(64))
    details_hash: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), server_default="PENDING")
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    job_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    match_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Application(Owned, Record, Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("candidate_id", "job_id", name="uq_application_candidate_job"),
        UniqueConstraint(
            "owner_account_id",
            "idempotency_key",
            name="uq_application_replay",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "state IN (" + ",".join(f"'{s.value}'" for s in State) + ")",
            name="ck_application_state",
        ),
        Index("ix_applications_state", "state"),
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"))
    state: Mapped[str] = mapped_column(String(40), default=State.DISCOVERED.value)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("approval_requests.id")
    )
    confirmation: Mapped[str | None] = mapped_column(Text)


class ApplicationEvent(Owned, Record, Base):
    __tablename__ = "application_events"
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    from_state: Mapped[str | None] = mapped_column(String(40))
    to_state: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(100), default="owner")


class NotificationDelivery(Owned, Record, Base):
    __tablename__ = "notification_deliveries"
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"))
    channel: Mapped[str] = mapped_column(String(30))
    deduplication_key: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(30))
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("notification_reports.id", name="fk_delivery_report"), index=True
    )
    error_code: Mapped[str | None] = mapped_column(String(80))
    provider_reference: Mapped[str | None] = mapped_column(String(200))


class AgentExecution(Owned, Record, Base):
    __tablename__ = "agent_executions"
    __table_args__ = (
        UniqueConstraint(
            "owner_account_id",
            "idempotency_key",
            name="uq_agent_execution_idempotency",
            postgresql_nulls_not_distinct=True,
        ),
    )
    agent_name: Mapped[str] = mapped_column(String(100), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(200), default=lambda: str(uuid.uuid4())
    )
    request_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DiscoveryItem(Owned, Record, Base):
    __tablename__ = "discovery_items"
    __table_args__ = (
        UniqueConstraint(
            "owner_account_id",
            "provider",
            "external_id",
            name="uq_discovery_provider_external_id",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "status IN ('REVIEW_REQUIRED', 'IMPORTED', 'CONFLICT', 'DISMISSED')",
            name="ck_discovery_item_status",
        ),
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_executions.id"), index=True)
    provider: Mapped[str] = mapped_column(String(100), index=True)
    external_id: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(30), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id"), index=True)
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobAnalysis(Owned, Record, Base):
    __tablename__ = "job_analyses"
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), unique=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(30))
    extractor_version: Mapped[str] = mapped_column(String(50))
    requirements: Mapped[dict[str, Any]] = mapped_column(JSON)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalEvent(Owned, Record, Base):
    __tablename__ = "approval_events"
    approval_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_requests.id"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(100), server_default="owner")
    reason: Mapped[str | None] = mapped_column(Text)


class NotificationSetting(Owned, Record, Base):
    __tablename__ = "notification_settings"
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id"), unique=True)
    enabled: Mapped[bool] = mapped_column(default=False)
    email_enabled: Mapped[bool] = mapped_column(default=True)
    whatsapp_enabled: Mapped[bool] = mapped_column(default=True)
    email: Mapped[str | None] = mapped_column(String(320))
    whatsapp_number: Mapped[str | None] = mapped_column(String(20))
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationReport(Owned, Record, Base):
    __tablename__ = "notification_reports"
    __table_args__ = (UniqueConstraint("candidate_id", "slot", name="uq_report_candidate_slot"),)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id"), index=True)
    slot: Mapped[str] = mapped_column(String(100))
    mode: Mapped[str] = mapped_column(String(10))
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30))


class WorkspaceAccount(Record, Base):
    __tablename__ = "workspace_accounts"
    __table_args__ = (
        CheckConstraint("role IN ('USER', 'ADMIN')", name="ck_account_role"),
        UniqueConstraint("google_sub", name="uq_workspace_google_sub"),
    )
    role: Mapped[str] = mapped_column(String(10), default="USER", server_default="USER")
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    google_sub: Mapped[str | None] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginSession(Record, Base):
    __tablename__ = "login_sessions"
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspace_accounts.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthThrottle(Base):
    __tablename__ = "auth_throttles"
    key: Mapped[str] = mapped_column(String(30), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer)


class GoogleLoginFlow(Record, Base):
    __tablename__ = "google_login_flows"
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    nonce: Mapped[str] = mapped_column(String(100))
    verifier: Mapped[str] = mapped_column(String(150))
    mode: Mapped[str] = mapped_column(String(20))
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspace_accounts.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    login_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("login_sessions.id"))


class AccountActionToken(Record, Base):
    __tablename__ = "account_action_tokens"
    __table_args__ = (
        CheckConstraint("purpose IN ('verify','reset')", name="ck_account_token_purpose"),
    )
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspace_accounts.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(10))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountSecurityEvent(Record, Base):
    __tablename__ = "account_security_events"
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspace_accounts.id"), index=True)
    action: Mapped[str] = mapped_column(String(50))


class GlobalUsageCounter(Base):
    __tablename__ = "global_usage_counters"
    __table_args__ = (CheckConstraint("used >= 0", name="ck_global_usage_nonnegative"),)
    action: Mapped[str] = mapped_column(String(30), primary_key=True)
    bucket: Mapped[date] = mapped_column(Date, primary_key=True)
    used: Mapped[int] = mapped_column(Integer, default=0)


class UsageCounter(Base):
    __tablename__ = "usage_counters"
    __table_args__ = (CheckConstraint("used >= 0", name="ck_usage_nonnegative"),)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace_accounts.id"), primary_key=True
    )
    action: Mapped[str] = mapped_column(String(30), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    used: Mapped[int] = mapped_column(Integer, default=0)


class AdminAudit(Record, Base):
    __tablename__ = "admin_audit"
    actor_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspace_accounts.id"))
    target_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspace_accounts.id"))
    method: Mapped[str] = mapped_column(String(10))
    resource: Mapped[str] = mapped_column(String(500))


# Composite foreign keys reject references to another workspace, including direct writes.
OWNED_TABLES = [table for table in Base.metadata.tables.values() if "owner_account_id" in table.c]
for _table in OWNED_TABLES:
    if "id" in _table.c:
        _table.append_constraint(
            UniqueConstraint("owner_account_id", "id", name=f"uq_owner_{_table.name}")
        )
for _table in OWNED_TABLES:
    for _fk in list(_table.foreign_keys):
        if _fk.column.table in OWNED_TABLES:
            _table.append_constraint(
                ForeignKeyConstraint(
                    ["owner_account_id", _fk.parent.name],
                    [
                        f"{_fk.column.table.name}.owner_account_id",
                        f"{_fk.column.table.name}.{_fk.column.name}",
                    ],
                    name=f"fk_owner_{_table.name}_{_fk.parent.name}",
                )
            )
