import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from app.domain.identity import canonical_url
from app.schemas import Input, JobCreate

DEFAULT_TERMS = [
    "Python",
    "FastAPI",
    "Backend",
    "AI Engineer",
    "LLM",
    "Generative AI",
    "Agentic",
    "Technical Lead",
    "Engineering Lead",
]


class DiscoveryQuery(Input):
    search_terms: list[Annotated[str, Field(min_length=2, max_length=100)]] = Field(
        default_factory=lambda: DEFAULT_TERMS.copy(),
        min_length=1,
        max_length=15,
    )
    max_items: int = Field(default=25, ge=1, le=100)
    posted_within_days: int | None = Field(default=None, ge=1, le=7)

    def relevant(self, title: str) -> bool:
        return any(term.casefold() in title.casefold() for term in self.search_terms)


class DiscoveryRequest(DiscoveryQuery):
    sources: list[Annotated[str, Field(pattern=r"^[a-z0-9_-]{1,80}$")]] = Field(
        default_factory=lambda: ["mock"],
        min_length=1,
        max_length=10,
    )
    idempotency_key: str = Field(
        default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=200
    )

    @field_validator("sources")
    @classmethod
    def unique_sources(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("Sources must be unique")
        return values


class SourceConfig(Input):
    name: str = Field(pattern=r"^[a-z0-9_-]{1,80}$")
    kind: Literal["mock", "greenhouse", "lever", "career_page", "brave", "tavily", "gmail"]
    enabled: bool = True
    company: str | None = Field(default=None, min_length=1, max_length=200)
    board: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    region: Literal["global", "eu"] = "global"
    url: str | None = Field(default=None, max_length=2000)
    permitted: bool = False

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if self.kind in {"greenhouse", "lever"} and (not self.board or not self.company):
            raise ValueError("Board and confirmed employer name are required")
        if self.kind == "career_page":
            if not self.url or not self.permitted:
                raise ValueError("Career page requires an explicitly permitted URL")
            canonical_url(self.url)
            if not self.url.startswith("https://"):
                raise ValueError("Career pages require HTTPS")
        return self


class Listing(Input):
    external_id: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=300)
    company: str | None = Field(default=None, min_length=1, max_length=300)
    description: str = Field(default="", max_length=200000)
    source_url: str = Field(max_length=2000)
    application_url: str | None = Field(default=None, max_length=2000)
    application_instructions: str | None = Field(default=None, max_length=20000)
    employer_job_id: str | None = Field(default=None, max_length=200)
    linkedin_job_id: str | None = Field(default=None, pattern=r"^\d{1,30}$")
    location: str | None = Field(default=None, max_length=300)
    geographic_restrictions: str | None = Field(default=None, max_length=3000)
    work_authorization: str | None = Field(default=None, max_length=3000)
    compensation: str | None = Field(default=None, max_length=500)
    pakistan_eligible: bool | None = None
    sponsorship: bool | None = None
    relocation_support: bool | None = None
    requires_review: bool = False
    posted_at: datetime | None = None
    posting_date_evidence: str | None = Field(default=None, max_length=200)

    @field_validator("source_url", "application_url")
    @classmethod
    def valid_url(cls, value: str | None) -> str | None:
        if value is not None:
            canonical_url(value)
        return value

    def as_job(self, provider: str) -> JobCreate:
        if not self.company or self.requires_review:
            raise ValueError("Employer/role information requires human review")
        return JobCreate(
            **self.model_dump(
                exclude={"external_id", "requires_review", "posted_at", "posting_date_evidence"}
            ),
            source_name=provider,
        )


class ProviderBatch(Input):
    items: list[Listing] = Field(default_factory=list)
    rejected: int = 0
    warnings: list[str] = Field(default_factory=list)


class EmailImport(Input):
    raw_email: str = Field(min_length=1, max_length=1000000)
    idempotency_key: str = Field(
        default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=200
    )
