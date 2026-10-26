import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.schemas import Input

Decision = Literal["QUALIFIED", "BELOW_THRESHOLD", "NOT_QUALIFIED", "INELIGIBLE", "REVIEW_REQUIRED"]
Importance = Literal["required", "preferred", "mentioned"]
ExperienceScope = Literal["general", "specific", "unknown"]
POLICY_VERSION = "matching-v1"

# Equivalences only; knowing one technology never implies another.
SKILL_ALIASES: dict[str, list[str]] = {
    "python": ["python"],
    "fastapi": ["fastapi"],
    "django": ["django"],
    "flask": ["flask"],
    "rest apis": ["rest api", "rest apis", "restful"],
    "microservices": ["microservices"],
    "distributed systems": ["distributed systems"],
    "mongodb": ["mongodb", "mongo db"],
    "sql server": ["mssql", "sql server"],
    "sql": ["sql"],
    "postgresql": ["postgresql", "postgres"],
    "redis": ["redis"],
    "rabbitmq": ["rabbitmq"],
    "kafka": ["kafka"],
    "docker": ["docker"],
    "kubernetes": ["kubernetes", "k8s"],
    "azure aks": ["azure aks", "aks"],
    "azure": ["azure"],
    "aws": ["aws", "amazon web services"],
    "gcp": ["gcp", "google cloud"],
    "git": ["git"],
    "next.js": ["next.js", "nextjs"],
    "typescript": ["typescript"],
    "javascript": ["javascript"],
    "react": ["react", "reactjs"],
    "tailwind css": ["tailwind"],
    "llm evaluation": ["llm evaluation", "evaluating llms"],
    "prompt engineering": ["prompt engineering"],
    "agentic workflows": ["agentic workflows"],
    "function calling": ["function calling"],
    "gpt-3": ["gpt-3"],
    "gpt-4": ["gpt-4"],
    "langgraph": ["langgraph"],
    "langchain": ["langchain"],
    "machine learning": ["machine learning"],
    "computer vision": ["computer vision"],
    "tensorflow": ["tensorflow"],
    "keras": ["keras"],
    "pytorch": ["pytorch"],
    "data pipelines": ["data pipelines"],
    "aggregation pipelines": ["aggregation pipelines"],
    "unit testing": ["unit testing", "unit tests"],
    "system design": ["system design"],
    "php": ["php"],
    "symfony": ["symfony"],
    "java": ["java"],
    "go": ["golang", "go programming", "go language"],
    "rust": ["rust"],
    "c++": ["c++"],
    "c#": ["c#"],
    "adobe commerce": ["adobe commerce", "magento"],
}


def contains_skill(text: str, skill: str) -> bool:
    aliases = SKILL_ALIASES.get(skill.casefold(), [skill.casefold()])
    return any(
        re.search(r"(?<![\w])" + re.escape(alias) + r"(?![\w])", text, re.I) for alias in aliases
    )


def known_skills(text: str) -> set[str]:
    return {skill for skill in SKILL_ALIASES if contains_skill(text, skill)}


class SkillRequirement(Input):
    skill: str = Field(min_length=1, max_length=150)
    importance: Importance
    evidence: str = Field(min_length=1, max_length=1500)
    alternatives: list[Annotated[str, Field(min_length=1, max_length=150)]] = Field(
        default_factory=list, max_length=20
    )


class Requirements(Input):
    skills: list[SkillRequirement] = Field(default_factory=list, max_length=100)
    minimum_years: float | None = Field(default=None, ge=0, le=60)
    experience_evidence: str | None = Field(default=None, max_length=1500)
    experience_scope: ExperienceScope = "unknown"
    warnings: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_skills(self) -> Self:
        if len({row.skill.casefold() for row in self.skills}) != len(self.skills):
            raise ValueError("Duplicate requirement skills")
        return self


class RequirementReview(Input):
    confirmed: Literal[True]
    requirements: Requirements


class MatchingRequest(Input):
    candidate_id: uuid.UUID
    job_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=100)
    threshold: int | None = Field(default=None, ge=0, le=100)
    extractor: Literal["rules", "openai"] = "rules"
    idempotency_key: str = Field(
        default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=180
    )

    @model_validator(mode="after")
    def unique_jobs(self) -> Self:
        if self.job_ids and len(set(self.job_ids)) != len(self.job_ids):
            raise ValueError("Job IDs must be unique")
        return self


class CandidateFacts(Input):
    verified: bool
    location: str | None = None
    verified_skills: list[str]
    unverified_skills: list[str] = Field(default_factory=list)
    experiences: list[dict[str, str | bool | list[str] | None]]
    preferences: dict[str, object] = Field(default_factory=dict)


class JobFacts(Input):
    title: str
    description: str
    location: str | None = None
    geographic_restrictions: str | None = None
    work_authorization: str | None = None
    pakistan_eligible: bool | None = None
    sponsorship: bool | None = None
    relocation_support: bool | None = None
    compensation: str | None = None


class MatchResult(Input):
    score: int = Field(ge=0, le=100)
    threshold: int
    decision: Decision
    matched_skills: list[str]
    missing_required_skills: list[str]
    missing_preferred_skills: list[str]
    unverified_skills: list[str]
    components: dict[str, int]
    reasons: list[str]
    industry_years_upper_bound: float
    industry_years_lower_bound: float
    eligibility: str
    salary: str
    remote_priority: int = 0
    as_of: date
    policy_version: str = POLICY_VERSION


# Kept here so optional salary validation is consistent across API and scoring.
Money = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
