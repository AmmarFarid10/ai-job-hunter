import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.identity import normalize
from app.models import (
    Candidate,
    CandidateEducation,
    CandidateExperience,
    CandidatePreference,
    CandidateSkill,
    ResumeDraft,
)
from app.repositories.common import require
from app.schemas import ProfileUpdate


def fields(record: Any, names: list[str]) -> dict[str, Any]:
    return {name: getattr(record, name) for name in names}


async def profile_view(session: AsyncSession, candidate: Candidate) -> dict[str, Any]:
    result = fields(candidate, ["id", "name", "email", "location", "summary", "verified"])
    collections: list[
        tuple[
            type[CandidateSkill] | type[CandidateExperience] | type[CandidateEducation],
            str,
            list[str],
        ]
    ] = [
        (CandidateSkill, "skills", ["name", "verified"]),
        (
            CandidateExperience,
            "experiences",
            [
                "employer",
                "title",
                "start_date",
                "end_date",
                "start_month",
                "end_month",
                "is_current",
                "bullets",
                "verified",
            ],
        ),
        (
            CandidateEducation,
            "education",
            ["institution", "degree", "start_year", "graduation_year", "verified"],
        ),
    ]
    for model, name, columns in collections:
        rows = await session.scalars(select(model).where(model.candidate_id == candidate.id))
        result[name] = [fields(row, columns) for row in rows]
    prefs = await session.scalar(
        select(CandidatePreference).where(CandidatePreference.candidate_id == candidate.id)
    )
    result["preferences"] = (
        fields(
            prefs,
            [
                "match_threshold",
                "roles",
                "locations",
                "remote_pakistan_priority",
                "minimum_annual_salary",
                "salary_currency",
                "open_to_relocation",
                "work_authorized_countries",
            ],
        )
        if prefs
        else None
    )
    warnings: list[str] = []
    for experience in result["experiences"]:
        if not experience["start_date"] and not experience["start_month"]:
            warnings.append(f"Missing start date: {experience['employer']}")
        if (
            not experience["end_date"]
            and not experience["end_month"]
            and not experience["is_current"]
        ):
            warnings.append(
                f"Confirm whether employment is current or missing an end date: "
                f"{experience['employer']}"
            )
    for education in result["education"]:
        if not education["graduation_year"]:
            warnings.append(f"Missing graduation year: {education['institution']}")
    result["review_warnings"] = warnings
    return result


async def update_profile(
    session: AsyncSession, candidate_id: uuid.UUID, data: ProfileUpdate
) -> Candidate:
    candidate = await require(session, Candidate, candidate_id, lock=True)
    for name in ["name", "email", "location", "summary"]:
        setattr(candidate, name, getattr(data, name))
    candidate.verified = True
    models: list[
        type[CandidateSkill]
        | type[CandidateExperience]
        | type[CandidateEducation]
        | type[CandidatePreference]
    ] = [
        CandidateSkill,
        CandidateExperience,
        CandidateEducation,
        CandidatePreference,
    ]
    for model in models:
        await session.execute(delete(model).where(model.candidate_id == candidate_id))
    for name in data.skills:
        session.add(
            CandidateSkill(
                candidate_id=candidate_id, name=name, normalized_name=normalize(name), verified=True
            )
        )
    for experience in data.experiences:
        session.add(
            CandidateExperience(candidate_id=candidate_id, verified=True, **experience.model_dump())
        )
    for education in data.education:
        session.add(
            CandidateEducation(candidate_id=candidate_id, verified=True, **education.model_dump())
        )
    session.add(CandidatePreference(candidate_id=candidate_id, **data.preferences.model_dump()))
    await session.flush()
    return candidate


async def confirm_draft(
    session: AsyncSession, candidate_id: uuid.UUID, draft_id: uuid.UUID, data: ProfileUpdate
) -> Candidate:
    # Keep lock order consistent with other profile updates.
    await require(session, Candidate, candidate_id, lock=True)
    draft = await require(session, ResumeDraft, draft_id, lock=True)
    if draft.candidate_id != candidate_id:
        raise HTTPException(404, "ResumeDraft not found")
    if draft.reviewed_at:
        raise HTTPException(409, "Draft already confirmed; update profile explicitly instead")
    candidate = await update_profile(session, candidate_id, data)
    draft.reviewed_at = datetime.now(UTC)
    draft.confirmed_profile = data.model_dump(mode="json")
    await session.flush()
    return candidate
