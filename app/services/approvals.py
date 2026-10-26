import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.approvals import ApprovalCreate, ApprovalDecision
from app.domain.states import State
from app.models import (
    Application,
    ApplicationEvent,
    ApprovalEvent,
    ApprovalRequest,
    Candidate,
    Job,
    JobMatch,
    ResumeVersion,
)
from app.repositories.common import require
from app.services.discovery import request_hash
from app.services.matching import match_view
from app.services.tailoring import artifact_bytes, inputs_current


def token_hash(token: str) -> str:
    return request_hash({"approval_token": token})


def job_binding(job: Job) -> str:
    return request_hash(
        {
            column.name: getattr(job, column.name)
            for column in Job.__table__.columns
            if column.name not in {"id", "created_at", "updated_at", "owner_account_id"}
        }
    )


def match_binding(match: JobMatch) -> str:
    return request_hash(
        {
            key: getattr(match, key)
            for key in [
                "profile_hash",
                "job_hash",
                "requirements_hash",
                "policy_version",
                "score",
                "threshold",
                "decision",
            ]
        }
    )


async def blockers(session: AsyncSession, row: ApprovalRequest) -> list[str]:
    version = await require(session, ResumeVersion, row.resume_version_id)
    job = await require(session, Job, row.job_id)
    match = await session.scalar(
        select(JobMatch).where(
            JobMatch.candidate_id == row.candidate_id, JobMatch.job_id == row.job_id
        )
    )
    reasons = []
    application = await session.scalar(
        select(Application).where(
            Application.candidate_id == row.candidate_id, Application.job_id == row.job_id
        )
    )
    expected_state = State.APPROVED if row.status == "APPROVED" else State.PENDING_APPROVAL
    if (
        application is None
        or application.approval_request_id != row.id
        or application.state != expected_state
    ):
        reasons.append("APPLICATION_REVIEW_NOT_CURRENT")
    if row.expires_at <= datetime.now(UTC):
        reasons.append("EXPIRED")
    if not row.details or request_hash(row.details) != row.details_hash:
        reasons.append("DETAILS_CHANGED")
    if row.job_snapshot_hash != job_binding(job):
        reasons.append("JOB_CHANGED")
    if match is None or not (await match_view(session, match))["qualified"]:
        reasons.append("MATCH_NOT_CURRENT_AND_QUALIFIED")
    elif row.match_snapshot_hash != match_binding(match):
        reasons.append("MATCH_INPUTS_CHANGED")
    if version.content_hash != row.resume_hash or not await inputs_current(session, version):
        reasons.append("RESUME_CHANGED_OR_STALE")
    if version.generation_mode != "qualified":
        reasons.append("REVIEW_DRAFT_REQUIRES_QUALIFIED_REGENERATION")
    if version.document_data and "MISSING_CONFIRMED_CONTACT_EMAIL" in version.document_data.get(
        "warnings", []
    ):
        reasons.append("MISSING_CONFIRMED_CONTACT_EMAIL")
    latest = await session.scalar(
        select(ResumeVersion.id)
        .where(ResumeVersion.candidate_id == row.candidate_id, ResumeVersion.job_id == row.job_id)
        .order_by(ResumeVersion.version.desc())
        .limit(1)
    )
    if latest != version.id:
        reasons.append("NEWER_RESUME_VERSION_EXISTS")
    try:
        for format in ["pdf", "docx"]:
            await artifact_bytes(version, format, get_settings())
    except HTTPException:
        reasons.append("ARTIFACT_INTEGRITY_FAILED")
    return reasons


async def approval_view(session: AsyncSession, row: ApprovalRequest) -> dict[str, Any]:
    reasons = await blockers(session, row)
    events = (
        await session.scalars(
            select(ApprovalEvent)
            .where(ApprovalEvent.approval_id == row.id)
            .order_by(ApprovalEvent.created_at, ApprovalEvent.id)
        )
    ).all()
    return {
        key: getattr(row, key)
        for key in [
            "id",
            "candidate_id",
            "job_id",
            "resume_version_id",
            "resume_hash",
            "details_hash",
            "details",
            "status",
            "reason",
            "created_at",
            "expires_at",
            "approved_at",
            "revoked_at",
            "decided_at",
        ]
    } | {
        "blockers": reasons,
        "effective_approved": row.status == "APPROVED" and not reasons,
        "can_approve": row.status == "PENDING" and not reasons,
        "events": [
            {
                "action": event.action,
                "reason": event.reason,
                "actor": event.actor,
                "created_at": event.created_at,
            }
            for event in events
        ],
    }


async def application_for(
    session: AsyncSession, candidate_id: uuid.UUID, job_id: uuid.UUID
) -> Application:
    application = await session.scalar(
        select(Application)
        .where(Application.candidate_id == candidate_id, Application.job_id == job_id)
        .with_for_update()
    )
    if application is None:
        application = Application(
            candidate_id=candidate_id,
            job_id=job_id,
            state=State.DISCOVERED.value,
            idempotency_key=f"review:{candidate_id}:{job_id}",
        )
        session.add(application)
        await session.flush()
        session.add(
            ApplicationEvent(
                application_id=application.id,
                from_state=None,
                to_state=State.DISCOVERED.value,
                reason="Created for human review",
                actor="review_workflow",
                created_at=datetime.now(UTC),
            )
        )
    return application


def move(session: AsyncSession, application: Application, target: State, reason: str) -> None:
    previous = application.state
    application.state = target.value
    session.add(
        ApplicationEvent(
            application_id=application.id,
            from_state=previous,
            to_state=target.value,
            reason=reason,
            actor="approval_workflow",
            created_at=datetime.now(UTC),
        )
    )


async def create_approval(session: AsyncSession, data: ApprovalCreate) -> dict[str, Any]:
    initial = await require(session, ResumeVersion, data.resume_version_id)
    await require(session, Candidate, initial.candidate_id, lock=True)
    job = await require(session, Job, initial.job_id, lock=True)
    if not data.details.valid_destination():
        raise HTTPException(422, "Use an HTTPS portal URL or valid email destination")
    if not await inputs_current(session, initial):
        raise HTTPException(409, "Generate a fresh resume before requesting review")
    # Request creation is allowed for review drafts; approval still requires qualification.
    application = await application_for(session, initial.candidate_id, initial.job_id)
    if application.state in {
        State.SUBMITTING,
        State.SUBMITTED,
        State.VERIFICATION_REQUIRED,
        State.REJECTED,
    }:
        raise HTTPException(409, "This application cannot start another review")
    existing = (
        await session.scalars(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.candidate_id == initial.candidate_id,
                ApprovalRequest.job_id == job.id,
                ApprovalRequest.status.in_(["PENDING", "APPROVED"]),
            )
            .with_for_update()
        )
    ).all()
    for row in existing:
        row.status = "REVOKED"
        row.revoked_at = datetime.now(UTC)
        session.add(
            ApprovalEvent(approval_id=row.id, action="SUPERSEDED", reason="New review request")
        )
    match = await session.scalar(
        select(JobMatch).where(
            JobMatch.candidate_id == initial.candidate_id, JobMatch.job_id == job.id
        )
    )
    token = secrets.token_urlsafe(32)
    row = ApprovalRequest(
        candidate_id=initial.candidate_id,
        job_id=job.id,
        resume_version_id=initial.id,
        resume_hash=initial.content_hash,
        details=data.details.model_dump(mode="json"),
        details_hash=request_hash(data.details.model_dump(mode="json")),
        token_hash=token_hash(token),
        status="PENDING",
        job_snapshot_hash=job_binding(job),
        match_snapshot_hash=match_binding(match) if match else None,
        expires_at=datetime.now(UTC) + timedelta(hours=data.expires_in_hours),
    )
    session.add(row)
    await session.flush()
    session.add(ApprovalEvent(approval_id=row.id, action="CREATED"))
    application.approval_request_id = row.id
    if application.state == State.DISCOVERED:
        move(session, application, State.MATCHED, "Match snapshot selected for review")
    if application.state == State.MATCHED:
        move(session, application, State.RESUME_GENERATED, "Immutable resume version selected")
    if application.state != State.PENDING_APPROVAL:
        move(session, application, State.PENDING_APPROVAL, "Awaiting exact-version human decision")
    await session.flush()
    return {
        **await approval_view(session, row),
        "token": token,
        "review_link": f"{get_settings().dashboard_url}/#approval={row.id}&token={token}",
    }


async def decide(
    session: AsyncSession, approval_id: uuid.UUID, data: ApprovalDecision
) -> dict[str, Any]:
    initial = await require(session, ApprovalRequest, approval_id)
    await require(session, Candidate, initial.candidate_id, lock=True)
    await require(session, Job, initial.job_id, lock=True)
    row = await require(session, ApprovalRequest, approval_id, lock=True)
    if data.token is not None and not secrets.compare_digest(
        token_hash(data.token), row.token_hash
    ):
        raise HTTPException(403, "Invalid review link")
    expected = "APPROVED" if data.action == "revoke" else "PENDING"
    if row.status != expected or row.revoked_at is not None:
        raise HTTPException(409, "Review request has already been decided or superseded")
    if data.action != "revoke" and row.expires_at <= datetime.now(UTC):
        raise HTTPException(409, "Review request has expired; create a new one")
    application = await application_for(session, row.candidate_id, row.job_id)
    if application.approval_request_id != row.id:
        raise HTTPException(409, "Review request is no longer current")
    if data.action == "approve":
        reasons = await blockers(session, row)
        if reasons:
            raise HTTPException(
                409, {"message": "Approval requirements unresolved", "blockers": reasons}
            )
        row.status = "APPROVED"
        row.approved_at = datetime.now(UTC)
        move(
            session,
            application,
            State.APPROVED,
            "Owner approved exact resume and application details",
        )
    elif data.action == "reject":
        row.status = "REJECTED"
        move(session, application, State.REJECTED, data.reason or "Owner rejected opportunity")
    elif data.action == "request_changes":
        if not data.reason.strip():
            raise HTTPException(422, "Describe the requested resume changes")
        row.status = "CHANGES_REQUESTED"
        move(session, application, State.ACTION_REQUIRED, data.reason)
    else:
        row.status = "REVOKED"
        row.revoked_at = datetime.now(UTC)
        move(session, application, State.PENDING_APPROVAL, "Owner revoked approval")
    row.reason = data.reason or None
    row.decided_at = datetime.now(UTC)
    session.add(ApprovalEvent(approval_id=row.id, action=row.status, reason=row.reason))
    await session.flush()
    return await approval_view(session, row)
