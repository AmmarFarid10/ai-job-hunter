import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.agents.tailoring import tailor_document
from app.config import Settings
from app.domain.matching import Requirements
from app.domain.tailoring import TAILORING_VERSION, TailoringRequest
from app.integrations.documents.render import render_resume
from app.integrations.documents.storage import (
    ArtifactError,
    digest,
    read_artifact,
    remove_artifacts,
    write_artifacts,
)
from app.models import AgentExecution, Job, JobAnalysis, JobMatch, ResumeVersion
from app.repositories.common import require
from app.repositories.matching import facts_hash, job_facts
from app.repositories.tailoring import load_resume_source
from app.services.discovery import request_hash
from app.services.matching import match_view
from app.services.quotas import reserve_usage


async def generation_lock(session: AsyncSession, key: str) -> None:
    lock_id = int.from_bytes(
        hashlib.sha256(("tailoring:" + key).encode()).digest()[:8], "big", signed=True
    )
    acquired = await session.scalar(text("SELECT pg_try_advisory_xact_lock(:id)"), {"id": lock_id})
    if not acquired:
        raise HTTPException(409, "This resume generation is already in progress")


def manifest_hash(document_data: dict[str, Any], docx_hash: str, pdf_hash: str) -> str:
    return request_hash(
        {"document_data": document_data, "docx_sha256": docx_hash, "pdf_sha256": pdf_hash}
    )


async def inputs_current(session: AsyncSession, row: ResumeVersion) -> bool:
    try:
        source = await load_resume_source(session, row.candidate_id)
    except ValueError:
        source = None
    job = await require(session, Job, row.job_id)
    analysis = await session.scalar(select(JobAnalysis).where(JobAnalysis.job_id == job.id))
    current = (
        source is not None
        and row.profile_hash == request_hash(source.model_dump(mode="json"))
        and row.job_hash == facts_hash(job_facts(job))
        and analysis is not None
        and row.requirements_hash == request_hash(analysis.requirements)
        and row.tailoring_version == TAILORING_VERSION
    )
    return current


async def version_view(session: AsyncSession, row: ResumeVersion) -> dict[str, Any]:
    current = await inputs_current(session, row)
    from app.models import ApprovalRequest
    from app.services.approvals import blockers

    approval = await session.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.resume_version_id == row.id, ApprovalRequest.status == "APPROVED")
        .order_by(ApprovalRequest.created_at.desc())
        .limit(1)
    )
    approved = approval is not None and not await blockers(session, approval)
    return {
        "id": row.id,
        "candidate_id": row.candidate_id,
        "job_id": row.job_id,
        "version": row.version,
        "status": row.status,
        "generation_mode": row.generation_mode,
        "approved": approved,
        "inputs_current": current,
        "created_at": row.created_at,
        "content_hash": row.content_hash,
        "docx_sha256": row.docx_sha256,
        "pdf_sha256": row.pdf_sha256,
        "document_data": row.document_data,
        "execution_id": row.execution_id,
        "downloads": {
            format: f"/api/v1/resumes/versions/{row.id}/download/{format}"
            for format in ["docx", "pdf"]
        },
    }


async def generate_resume(
    session: AsyncSession, request: TailoringRequest, settings: Settings
) -> dict[str, Any]:
    await generation_lock(session, request.idempotency_key)
    try:
        source = await load_resume_source(session, request.candidate_id, lock=True)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    job = await require(session, Job, request.job_id, lock=True)
    analysis = await session.scalar(select(JobAnalysis).where(JobAnalysis.job_id == job.id))
    match = await session.scalar(
        select(JobMatch).where(
            JobMatch.candidate_id == request.candidate_id, JobMatch.job_id == job.id
        )
    )
    if analysis is None or match is None:
        raise HTTPException(409, "Run matching for this candidate/job before tailoring")
    profile_hash = request_hash(source.model_dump(mode="json"))
    job_hash = facts_hash(job_facts(job))
    requirements_hash = request_hash(analysis.requirements)
    payload = {
        "request": request.model_dump(mode="json", exclude={"idempotency_key"}),
        "profile_hash": profile_hash,
        "job_hash": job_hash,
        "requirements_hash": requirements_hash,
        "tailoring_version": TAILORING_VERSION,
    }
    key = "tailoring:" + request.idempotency_key
    existing = await session.scalar(
        select(AgentExecution).where(AgentExecution.idempotency_key == key)
    )
    if existing:
        if existing.agent_name != "resume_tailoring" or existing.request_hash != request_hash(
            payload
        ):
            raise HTTPException(409, "Generation inputs changed; use a new idempotency key")
        row = await session.scalar(
            select(ResumeVersion).where(ResumeVersion.execution_id == existing.id)
        )
        if row is None:
            raise HTTPException(409, "Stored generation has no artifact version")
        return {**await version_view(session, row), "replayed": True}
    view = await match_view(session, match)
    if view["stale"]:
        raise HTTPException(409, "Match is stale; rerun matching before generating a new version")
    if request.mode == "qualified" and not view["qualified"]:
        raise HTTPException(
            409, "Job is not qualified; unresolved high-score jobs need explicit review mode"
        )
    if request.mode == "review" and (
        match.score < match.threshold or match.decision not in {"QUALIFIED", "REVIEW_REQUIRED"}
    ):
        raise HTTPException(
            409, "Review drafts require a threshold-passing qualified or review-required match"
        )
    requirements = Requirements.model_validate(analysis.requirements)
    try:
        await reserve_usage(session, "generation")
        document = await tailor_document(source, requirements, request.max_bullets_per_role)
        rendered = await run_in_threadpool(render_resume, document)
    except ValueError as exc:
        # Do not expose raw parser exceptions that could contain profile/document text.
        raise HTTPException(
            422, "Verified dates or generated document could not be rendered safely"
        ) from exc
    warnings = []
    if request.mode == "review":
        warnings.append("REVIEW_DRAFT_UNRESOLVED_MATCH_CHECKS")
    if not source.email:
        warnings.append("MISSING_CONFIRMED_CONTACT_EMAIL")
    if source.excluded_unverified_count:
        warnings.append("UNVERIFIED_PROFILE_RECORDS_EXCLUDED")
    if any(not row.graduation_year for row in source.education):
        warnings.append("EDUCATION_DATES_INCOMPLETE")
    data = {
        "document": document.model_dump(mode="json"),
        "verified_source": source.model_dump(mode="json"),
        "warnings": warnings,
        "match_snapshot": view["explanation"],
        "pdf_pages": rendered.pages,
        "tailoring_version": TAILORING_VERSION,
    }
    execution = AgentExecution(
        agent_name="resume_tailoring",
        status="COMPLETED",
        idempotency_key=key,
        request_hash=request_hash(payload),
        completed_at=datetime.now(UTC),
        summary={},
    )
    session.add(execution)
    await session.flush()
    number = (
        int(
            await session.scalar(
                select(func.coalesce(func.max(ResumeVersion.version), 0)).where(
                    ResumeVersion.candidate_id == request.candidate_id,
                    ResumeVersion.job_id == job.id,
                )
            )
            or 0
        )
        + 1
    )
    version_id = uuid.uuid4()
    docx_hash, pdf_hash = digest(rendered.docx), digest(rendered.pdf)
    keys: tuple[str, str] | None = None
    commit_attempted = False
    try:
        keys = await run_in_threadpool(
            write_artifacts, settings.storage_dir, version_id, rendered.docx, rendered.pdf
        )
        row = ResumeVersion(
            id=version_id,
            candidate_id=request.candidate_id,
            job_id=job.id,
            version=number,
            content_hash=manifest_hash(data, docx_hash, pdf_hash),
            storage_key=keys[0],
            pdf_storage_key=keys[1],
            docx_sha256=docx_hash,
            pdf_sha256=pdf_hash,
            document_data=data,
            profile_hash=profile_hash,
            job_hash=job_hash,
            requirements_hash=requirements_hash,
            tailoring_version=TAILORING_VERSION,
            generation_mode=request.mode,
            status="DRAFT_REVIEW" if request.mode == "review" else "DRAFT",
            execution_id=execution.id,
        )
        session.add(row)
        execution.summary = {
            "resume_version_id": str(version_id),
            "version": number,
            "candidate_id": str(request.candidate_id),
            "job_id": str(job.id),
            "mode": request.mode,
            "pages": rendered.pages,
            "warnings": warnings,
        }
        await session.flush()
        result = {**await version_view(session, row), "replayed": False}
        commit_attempted = True
        await session.commit()
        return result
    except BaseException:
        # If commit outcome is uncertain, preserve bytes for reconciliation rather than
        # deleting artifacts that a committed version may reference.
        if keys and not commit_attempted:
            await run_in_threadpool(remove_artifacts, settings.storage_dir, keys)
        raise


async def artifact_bytes(row: ResumeVersion, format: str, settings: Settings) -> bytes:
    if (
        not row.document_data
        or not row.docx_sha256
        or not row.pdf_sha256
        or not row.pdf_storage_key
    ):
        raise HTTPException(409, "Legacy resume version has no validated artifact manifest")
    if row.content_hash != manifest_hash(row.document_data, row.docx_sha256, row.pdf_sha256):
        raise HTTPException(409, "Resume manifest integrity check failed")
    key, checksum = (
        (row.storage_key, row.docx_sha256)
        if format == "docx"
        else (row.pdf_storage_key, row.pdf_sha256)
    )
    try:
        return await run_in_threadpool(read_artifact, settings.storage_dir, key, checksum)
    except ArtifactError as exc:
        raise HTTPException(
            409, "Resume artifact missing or modified; generate a new version"
        ) from exc
