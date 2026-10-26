import re
import uuid
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApplicationDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["manual_handoff", "email", "career_portal"] = "manual_handoff"
    destination: str = Field(min_length=3, max_length=2000)
    cover_letter: str = Field(default="", max_length=15000)
    screening_answers: dict[str, str] = Field(default_factory=dict, max_length=50)

    @field_validator("screening_answers")
    @classmethod
    def bounded_answers(cls, value: dict[str, str]) -> dict[str, str]:
        if any(len(key) > 500 or len(answer) > 4000 for key, answer in value.items()):
            raise ValueError("Screening question or answer too long")
        return value

    @field_validator("destination")
    @classmethod
    def destination_format(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("Invalid destination")
        return value

    def valid_destination(self) -> bool:
        if self.method == "email":
            return bool(re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", self.destination))
        parsed = urlsplit(self.destination)
        return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username


class ApprovalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resume_version_id: uuid.UUID
    details: ApplicationDetails
    expires_in_hours: int = Field(default=24, ge=1, le=72)


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "reject", "request_changes", "revoke"]
    confirmed: Literal[True]
    reason: str = Field(default="", max_length=4000)
    token: str | None = Field(default=None, min_length=32, max_length=200)


class NotificationPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    email_enabled: bool = True
    whatsapp_enabled: bool = True
    email: str | None = Field(
        default=None, max_length=320, pattern=r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$"
    )
    whatsapp_number: str | None = Field(default=None, pattern=r"^\+[1-9][0-9]{7,14}$")
    consent: bool = False
