from difflib import SequenceMatcher
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.identity import canonical_url, fingerprint, identity_keys, normalize
from app.models import Job, JobIdentity, JobSource
from app.repositories.jobs import find_identity_jobs, lock_identities
from app.schemas import JobCreate


async def create_job(session: AsyncSession, data: JobCreate) -> tuple[Job, bool, list[str]]:
    keys = identity_keys(
        **data.model_dump(
            include={
                "company",
                "title",
                "description",
                "source_url",
                "application_url",
                "employer_job_id",
                "linkedin_job_id",
            }
        )
    )
    from app.ownership import identity_key

    keys = [identity_key(session.sync_session, key) for key in keys]
    await lock_identities(session, keys)
    existing_ids = await find_identity_jobs(session, keys)
    if len(existing_ids) > 1:
        raise HTTPException(409, "Conflicting vacancy identities require manual review")
    created = not existing_ids
    if existing_ids:
        job = await session.scalar(select(Job).where(Job.id.in_(existing_ids)).with_for_update())
        assert job is not None
        # An exact source URL must not override a conflicting employer or LinkedIn ID.
        for field in ["employer_job_id", "linkedin_job_id"]:
            old, new = getattr(job, field), getattr(data, field)
            if old and new and old != new:
                raise HTTPException(409, f"Conflicting {field}; manual review required")
        if job.normalized_company != normalize(data.company):
            raise HTTPException(409, "Conflicting company identity; manual review required")
        for field in ["employer_job_id", "linkedin_job_id"]:
            if getattr(job, field) is None and getattr(data, field) is not None:
                setattr(job, field, getattr(data, field))
    else:
        values = data.model_dump(exclude={"source_name", "source_url"})
        if data.application_url:
            values["application_url"] = canonical_url(data.application_url)
        job = Job(
            **values,
            normalized_title=normalize(data.title),
            normalized_company=normalize(data.company),
            description_fingerprint=fingerprint(data.description),
        )
        session.add(job)
        await session.flush()
    # Preserve first-source facts; new observations remain in job_sources for review.
    for key in keys:
        if await session.get(JobIdentity, key) is None:
            session.add(JobIdentity(key=key, job_id=job.id))
    url = canonical_url(data.source_url)
    source = await session.scalar(
        select(JobSource).where(
            JobSource.job_id == job.id,
            JobSource.canonical_url == url,
        )
    )
    if source is None:
        session.add(
            JobSource(
                job_id=job.id,
                provider=data.source_name,
                url=data.source_url,
                canonical_url=url,
                description=data.description,
            )
        )
    candidates = await session.scalars(
        select(Job)
        .where(
            Job.normalized_company == job.normalized_company,
            Job.id != job.id,
        )
        .limit(100)
    )
    possible = [
        str(row.id)
        for row in candidates
        if SequenceMatcher(None, job.normalized_title, row.normalized_title).ratio() >= 0.8
    ]
    await session.flush()
    return job, created, possible


async def job_view(session: AsyncSession, job: Job) -> dict[str, Any]:
    result = {column.name: getattr(job, column.name) for column in Job.__table__.columns}
    sources = await session.scalars(select(JobSource).where(JobSource.job_id == job.id))
    result["sources"] = [
        {"id": row.id, "provider": row.provider, "url": row.url} for row in sources
    ]
    return result
