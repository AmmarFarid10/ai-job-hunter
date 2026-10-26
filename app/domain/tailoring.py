import calendar
import re
import uuid
from datetime import date
from typing import Literal

from pydantic import Field

from app.domain.matching import Requirements, known_skills
from app.schemas import Input

TAILORING_VERSION = "tailoring-v1"


class TailoringRequest(Input):
    candidate_id: uuid.UUID
    job_id: uuid.UUID
    mode: Literal["qualified", "review"] = "qualified"
    max_bullets_per_role: int = Field(default=5, ge=1, le=10)
    idempotency_key: str = Field(
        default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=180
    )


class SourceSkill(Input):
    id: str
    name: str


class SourceExperience(Input):
    id: str
    employer: str
    title: str
    start_date: str | None = None
    end_date: str | None = None
    start_month: str | None = None
    end_month: str | None = None
    is_current: bool | None = None
    bullets: list[str]


class SourceEducation(Input):
    id: str
    institution: str
    degree: str
    start_year: int | None = None
    graduation_year: int | None = None


class ResumeSource(Input):
    name: str
    email: str | None = None
    location: str | None = None
    skills: list[SourceSkill]
    experiences: list[SourceExperience]
    education: list[SourceEducation]
    excluded_unverified_count: int = 0


class ResumeBullet(Input):
    source_index: int
    text: str


class ResumeRole(Input):
    source_id: str
    employer: str
    title: str
    dates: str
    bullets: list[ResumeBullet]
    omitted_bullet_indices: list[int]


class ResumeEducation(Input):
    source_id: str
    institution: str
    degree: str
    dates: str


class ResumeDocument(Input):
    name: str
    email: str | None
    location: str | None
    headline: str
    summary: str
    skills: list[SourceSkill]
    experiences: list[ResumeRole]
    education: list[ResumeEducation]


def clean_bullet(text: str) -> str:
    # Repair PDF wrapping/typography only. Preserve words, numbers, tense and attribution.
    return re.sub(r"(?<=\w)-\s+(?=\w)", "-", " ".join(text.split()))


def date_label(full: str | None, month: str | None) -> str | None:
    if full:
        value = date.fromisoformat(full)
        return f"{calendar.month_abbr[value.month]} {value.day}, {value.year}"
    if month:
        year, number = map(int, month.split("-"))
        return f"{calendar.month_abbr[number]} {year}"
    return None


def role_dates(row: SourceExperience) -> str:
    start = date_label(row.start_date, row.start_month)
    end = date_label(row.end_date, row.end_month)
    if not start or not end and row.is_current is not True:
        raise ValueError(
            "Verified employment needs a start and end boundary, or confirmed current status"
        )
    return f"{start} - {'Present' if row.is_current else end}"


def education_dates(row: SourceEducation) -> str:
    if row.start_year and row.graduation_year:
        return f"{row.start_year} - {row.graduation_year}"
    if row.graduation_year:
        return str(row.graduation_year)
    if row.start_year:
        return f"Started {row.start_year}"
    return ""


def build_document(
    source: ResumeSource, requirements: Requirements, maximum: int
) -> ResumeDocument:
    if not source.experiences:
        raise ValueError("At least one verified employment record is required")
    relevant = {row.skill.casefold() for row in requirements.skills}
    relevant.update(value.casefold() for row in requirements.skills for value in row.alternatives)

    def relevance(text: str) -> int:
        return len((known_skills(text) | {text.casefold()}) & relevant)

    skills = sorted(
        source.skills, key=lambda row: (-relevance(row.name), row.name.casefold(), row.id)
    )
    experiences = sorted(
        source.experiences,
        key=lambda row: (row.is_current is True, row.start_date or row.start_month or "", row.id),
        reverse=True,
    )
    current = [row for row in experiences if row.is_current is True]
    headline = (current or experiences)[0].title
    family = (
        "Backend engineering professional"
        if any("backend" in row.title.casefold() for row in experiences)
        else "Professional"
    )
    summary = family
    if skills:
        summary += " with experience in " + ", ".join(row.name for row in skills[:6])
    summary += "."
    lead = next(
        (row for row in experiences if re.search(r"\b(?:lead|manager)\b", row.title, re.I)), None
    )
    if lead:
        summary += f" Technical leadership experience as {lead.title} at {lead.employer}."
    roles = []
    for row in experiences:
        order = sorted(
            range(len(row.bullets)), key=lambda index: (-relevance(row.bullets[index]), index)
        )
        chosen = order[:maximum]
        roles.append(
            ResumeRole(
                source_id=row.id,
                employer=row.employer,
                title=row.title,
                dates=role_dates(row),
                bullets=[
                    ResumeBullet(source_index=index, text=clean_bullet(row.bullets[index]))
                    for index in chosen
                ],
                omitted_bullet_indices=[
                    index for index in range(len(row.bullets)) if index not in chosen
                ],
            )
        )
    education = sorted(
        source.education, key=lambda row: (row.graduation_year or 0, row.id), reverse=True
    )
    return ResumeDocument(
        name=source.name,
        email=source.email,
        location=source.location,
        headline=headline,
        summary=summary,
        skills=skills,
        experiences=roles,
        education=[
            ResumeEducation(
                source_id=row.id,
                institution=row.institution,
                degree=row.degree,
                dates=education_dates(row),
            )
            for row in education
        ],
    )


def validate_document(
    document: ResumeDocument, source: ResumeSource, requirements: Requirements, maximum: int
) -> None:
    # Rebuilding from verified inputs validates every claim, date and source index.
    expected = build_document(source, requirements, maximum)
    if document.model_dump() != expected.model_dump():
        raise ValueError("Tailored content does not match verified source facts")
