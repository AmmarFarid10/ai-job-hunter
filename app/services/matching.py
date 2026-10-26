from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.matching import POLICY_VERSION, Requirements
from app.integrations.discovery.base import ProviderError
from app.integrations.matching.rules import RequirementExtractor, validate_evidence
from app.models import Job, JobAnalysis, JobMatch, JobRequirement
from app.repositories.matching import facts_hash, job_facts, load_candidate, today
from app.services.discovery import request_hash

EXTRACTOR_VERSION = "requirements-v1"


async def save_analysis(
    session: AsyncSession,
    job: Job,
    requirements: Requirements,
    method: str,
    *,
    reviewed: bool = False,
) -> JobAnalysis:
    validate_evidence(requirements, job.title, job.description)
    analysis = await session.scalar(select(JobAnalysis).where(JobAnalysis.job_id == job.id))
    if analysis is None:
        analysis = JobAnalysis(job_id=job.id)
        session.add(analysis)
    analysis.content_hash = facts_hash(job_facts(job))
    analysis.method = method
    analysis.extractor_version = EXTRACTOR_VERSION
    analysis.requirements = requirements.model_dump(mode="json")
    analysis.reviewed_at = datetime.now(UTC) if reviewed else None
    await session.execute(delete(JobRequirement).where(JobRequirement.job_id == job.id))
    for row in requirements.skills:
        session.add(
            JobRequirement(
                job_id=job.id,
                category="skill",
                value=row.skill,
                required=row.importance == "required",
            )
        )
    await session.flush()
    return analysis


async def get_analysis(
    session: AsyncSession, job: Job, extractor: RequirementExtractor, method: str
) -> JobAnalysis:
    existing = await session.scalar(select(JobAnalysis).where(JobAnalysis.job_id == job.id))
    if (
        existing
        and existing.content_hash == facts_hash(job_facts(job))
        and (existing.method in {method, "owner"})
        and existing.extractor_version == EXTRACTOR_VERSION
    ):
        return existing
    requirements = await extractor.extract(job.title, job.description)
    return await save_analysis(session, job, requirements, method)


def analysis_view(analysis: JobAnalysis, job: Job) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "method": analysis.method,
        "requirements": analysis.requirements,
        "reviewed_at": analysis.reviewed_at,
        "stale": analysis.content_hash != facts_hash(job_facts(job)),
    }


async def match_view(
    session: AsyncSession, match: JobMatch, current_profile_hash: str | None = None
) -> dict[str, Any]:
    if current_profile_hash is None:
        current_profile_hash = facts_hash(await load_candidate(session, match.candidate_id))
    job = await session.get(Job, match.job_id)
    assert job is not None
    analysis = await session.scalar(select(JobAnalysis).where(JobAnalysis.job_id == match.job_id))
    stale = (
        match.profile_hash != current_profile_hash
        or match.job_hash != facts_hash(job_facts(job))
        or analysis is None
        or match.requirements_hash != request_hash(analysis.requirements)
        or match.as_of != today()
        or match.policy_version != POLICY_VERSION
    )
    return {
        "id": match.id,
        "candidate_id": match.candidate_id,
        "job_id": match.job_id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "score": match.score,
        "threshold": match.threshold,
        "decision": match.decision,
        "qualified": not stale and match.decision == "QUALIFIED",
        "stale": stale,
        "explanation": match.explanation,
        "execution_id": match.execution_id,
        "as_of": match.as_of,
        "updated_at": match.updated_at,
    }


def evidence_error(exc: ProviderError) -> HTTPException:
    return HTTPException(422, exc.code)
