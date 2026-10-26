import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.identity import canonical_url, normalize
from app.domain.preferences import DEFAULT_LOCATIONS, DEFAULT_ROLES
from app.domain.states import State

Name = Annotated[str, Field(min_length=1, max_length=200)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CandidateCreate(Input):
    name: Name
    email: str | None = Field(default=None, max_length=320)
    location: str | None = Field(default=None, max_length=200)


class Experience(Input):
    employer: Name
    title: Name
    start_date: date | None = None
    end_date: date | None = None
    start_month: str | None = Field(default=None, pattern=r"^[1-9]\d{3}-(0[1-9]|1[0-2])$")
    end_month: str | None = Field(default=None, pattern=r"^[1-9]\d{3}-(0[1-9]|1[0-2])$")
    is_current: bool | None = None
    bullets: list[Annotated[str, Field(max_length=2000)]] = Field(
        default_factory=list, max_length=100
    )

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.start_date and self.start_month or self.end_date and self.end_month:
            raise ValueError("Supply a full date or a month for each boundary, not both")
        if self.is_current and (self.end_date or self.end_month):
            raise ValueError("Current employment cannot have an end date/month")
        start = self.start_month or (self.start_date.strftime("%Y-%m") if self.start_date else None)
        end = self.end_month or (self.end_date.strftime("%Y-%m") if self.end_date else None)
        if start and end and end < start:
            raise ValueError("End month precedes start month")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("End date precedes start date")
        return self


class Education(Input):
    institution: Name
    degree: Name
    graduation_year: int | None = Field(default=None, ge=1900, le=2200)
    start_year: int | None = Field(default=None, ge=1900, le=2200)

    @model_validator(mode="after")
    def validate_years(self) -> Self:
        if self.start_year and self.graduation_year and self.graduation_year < self.start_year:
            raise ValueError("Graduation year precedes start year")
        return self


class Preferences(Input):
    match_threshold: int = Field(default=80, ge=0, le=100)
    roles: list[Name] = Field(default_factory=lambda: DEFAULT_ROLES.copy(), max_length=50)
    locations: list[Name] = Field(default_factory=lambda: DEFAULT_LOCATIONS.copy(), max_length=50)
    remote_pakistan_priority: bool = True
    minimum_annual_salary: Decimal | None = Field(
        default=None, gt=0, max_digits=14, decimal_places=2
    )
    salary_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    open_to_relocation: bool | None = None
    work_authorized_countries: list[Name] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def salary_has_currency(self) -> Self:
        if self.minimum_annual_salary is not None and self.salary_currency is None:
            raise ValueError("Minimum annual salary requires an explicit currency")
        return self


class ProfileUpdate(CandidateCreate):
    confirmed: bool
    summary: str | None = Field(default=None, max_length=10000)
    skills: list[Name] = Field(default_factory=list, max_length=200)
    experiences: list[Experience] = Field(default_factory=list, max_length=100)
    education: list[Education] = Field(default_factory=list, max_length=50)
    preferences: Preferences = Field(default_factory=Preferences)

    @field_validator("confirmed")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Explicit confirmation is required to verify profile facts")
        return value

    @field_validator("skills")
    @classmethod
    def unique_skills(cls, values: list[str]) -> list[str]:
        if any(not normalize(value) for value in values):
            raise ValueError("Skills must contain letters or numbers")
        if len({normalize(value) for value in values}) != len(values):
            raise ValueError("Duplicate normalized skills")
        return values


class JobCreate(Input):
    title: Annotated[str, Field(min_length=1, max_length=300)]
    company: Annotated[str, Field(min_length=1, max_length=300)]
    description: str = Field(default="", max_length=200000)
    source_name: Annotated[str, Field(min_length=1, max_length=100)]
    source_url: Annotated[str, Field(max_length=2000)]
    application_url: str | None = Field(default=None, max_length=2000)
    application_instructions: str | None = Field(default=None, max_length=20000)
    employer_job_id: Name | None = None
    linkedin_job_id: str | None = Field(default=None, pattern=r"^\d{1,30}$")
    location: str | None = Field(default=None, max_length=300)
    work_authorization: str | None = Field(default=None, max_length=3000)
    geographic_restrictions: str | None = Field(default=None, max_length=3000)
    pakistan_eligible: bool | None = None
    relocation_support: bool | None = None
    sponsorship: bool | None = None
    compensation: str | None = Field(default=None, max_length=500)

    @field_validator("source_url", "application_url")
    @classmethod
    def valid_url(cls, value: str | None) -> str | None:
        if value is not None:
            canonical_url(value)
        return value

    @field_validator("title", "company")
    @classmethod
    def meaningful(cls, value: str) -> str:
        if not normalize(value):
            raise ValueError("Value must contain letters or numbers")
        return value


class ApplicationCreate(Input):
    candidate_id: uuid.UUID
    job_id: uuid.UUID
    idempotency_key: str = Field(
        default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=200
    )


class Transition(Input):
    state: State
    reason: str | None = Field(default=None, max_length=2000)


class PreferenceReview(Input):
    confirmed: Literal[True]
    preferences: Preferences
