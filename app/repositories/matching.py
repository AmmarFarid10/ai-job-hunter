import uuid
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.matching import CandidateFacts, JobFacts
from app.models import Candidate, CandidateExperience, CandidatePreference, CandidateSkill, Job
from app.repositories.common import require
from app.services.discovery import request_hash


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Karachi")).date()


async def load_candidate(
    session: AsyncSession, candidate_id: uuid.UUID, *, lock: bool = False
) -> CandidateFacts:
    candidate = await require(session, Candidate, candidate_id, lock=lock)
    skills = (
        await session.scalars(
            select(CandidateSkill).where(CandidateSkill.candidate_id == candidate_id)
        )
    ).all()
    experience = (
        await session.scalars(
            select(CandidateExperience)
            .where(CandidateExperience.candidate_id == candidate_id)
            .order_by(CandidateExperience.id)
        )
    ).all()
    prefs = await session.scalar(
        select(CandidatePreference).where(CandidatePreference.candidate_id == candidate_id)
    )
    preferences: dict[str, Any] = {}
    if prefs:
        for field in [
            "roles",
            "locations",
            "match_threshold",
            "remote_pakistan_priority",
            "minimum_annual_salary",
            "salary_currency",
            "open_to_relocation",
            "work_authorized_countries",
        ]:
            value = getattr(prefs, field)
            preferences[field] = (
                str(value) if field == "minimum_annual_salary" and value is not None else value
            )
    rows = []
    for row in experience:
        values: dict[str, Any] = {
            key: getattr(row, key)
            for key in [
                "title",
                "employer",
                "verified",
                "is_current",
                "start_month",
                "end_month",
                "bullets",
            ]
        }
        values["start_date"] = row.start_date.isoformat() if row.start_date else None
        values["end_date"] = row.end_date.isoformat() if row.end_date else None
        rows.append(values)
    return CandidateFacts(
        verified=candidate.verified,
        location=candidate.location,
        verified_skills=sorted(row.name for row in skills if row.verified),
        unverified_skills=sorted(row.name for row in skills if not row.verified),
        experiences=rows,
        preferences=preferences,
    )


def job_facts(job: Job) -> JobFacts:
    return JobFacts(**{field: getattr(job, field) for field in JobFacts.model_fields})


def facts_hash(value: CandidateFacts | JobFacts) -> str:
    return request_hash(value.model_dump(mode="json"))


async def select_jobs(session: AsyncSession, job_ids: list[uuid.UUID] | None) -> list[Job]:
    query = select(Job).order_by(Job.id).with_for_update()
    if job_ids:
        query = query.where(Job.id.in_(job_ids))
    rows = list((await session.scalars(query.limit(101))).all())
    if job_ids and {row.id for row in rows} != set(job_ids):
        raise HTTPException(404, "One or more requested jobs were not found")
    if len(rows) > 100:
        raise HTTPException(422, "Select at most 100 explicit job IDs for a matching batch")
    return rows
