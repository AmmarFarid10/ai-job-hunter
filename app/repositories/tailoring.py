import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.tailoring import ResumeSource, SourceEducation, SourceExperience, SourceSkill
from app.models import Candidate, CandidateEducation, CandidateExperience, CandidateSkill
from app.repositories.common import require


async def load_resume_source(
    session: AsyncSession, candidate_id: uuid.UUID, *, lock: bool = False
) -> ResumeSource:
    candidate = await require(session, Candidate, candidate_id, lock=lock)
    if not candidate.verified:
        raise ValueError("Candidate profile has not been confirmed")
    skills = list(
        (
            await session.scalars(
                select(CandidateSkill)
                .where(CandidateSkill.candidate_id == candidate_id)
                .order_by(CandidateSkill.id)
            )
        ).all()
    )
    experiences = list(
        (
            await session.scalars(
                select(CandidateExperience)
                .where(CandidateExperience.candidate_id == candidate_id)
                .order_by(CandidateExperience.id)
            )
        ).all()
    )
    education = list(
        (
            await session.scalars(
                select(CandidateEducation)
                .where(CandidateEducation.candidate_id == candidate_id)
                .order_by(CandidateEducation.id)
            )
        ).all()
    )
    return ResumeSource(
        name=candidate.name,
        email=candidate.email,
        location=candidate.location,
        skills=[SourceSkill(id=str(row.id), name=row.name) for row in skills if row.verified],
        experiences=[
            SourceExperience(
                id=str(row.id),
                employer=row.employer,
                title=row.title,
                start_date=row.start_date.isoformat() if row.start_date else None,
                end_date=row.end_date.isoformat() if row.end_date else None,
                start_month=row.start_month,
                end_month=row.end_month,
                is_current=row.is_current,
                bullets=row.bullets,
            )
            for row in experiences
            if row.verified
        ],
        education=[
            SourceEducation(
                id=str(row.id),
                institution=row.institution,
                degree=row.degree,
                start_year=row.start_year,
                graduation_year=row.graduation_year,
            )
            for row in education
            if row.verified
        ],
        excluded_unverified_count=sum(not row.verified for row in skills)
        + sum(not row.verified for row in experiences)
        + sum(not row.verified for row in education),
    )
