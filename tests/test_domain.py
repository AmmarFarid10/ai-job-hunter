import pytest
from pydantic import ValidationError

from app.config import Settings
from app.domain.identity import canonical_url, identity_keys, normalize
from app.domain.states import State, validate_transition
from app.schemas import ProfileUpdate


def test_normalization_and_tracking() -> None:
    assert normalize(" ACME, Inc. ") == "acme inc"
    assert canonical_url("https://WWW.Example.com/jobs/42/?utm_source=x&b=2&a=1#top") == (
        "https://example.com/jobs/42?a=1&b=2"
    )
    # Query parameters which identify different jobs must survive canonicalization.
    assert canonical_url("https://example.com/apply?job=1") != canonical_url(
        "https://example.com/apply?job=2"
    )


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "javascript:alert(1)", "https://user:pass@example.com/job"]
)
def test_invalid_urls(url: str) -> None:
    with pytest.raises(ValueError):
        canonical_url(url)


def test_linkedin_id_cross_source() -> None:
    first = identity_keys(
        company="Acme",
        title="Python",
        description="",
        source_url="https://www.linkedin.com/jobs/view/python-engineer-123456/?trk=foo",
    )
    second = identity_keys(
        company="Acme",
        title="Python",
        description="",
        source_url="https://example.com/jobs/123",
        linkedin_job_id="123456",
    )
    assert set(first) & set(second)
    assert all(not key.startswith("content:") for key in first)


@pytest.mark.parametrize("state", list(State))
def test_same_state_is_invalid(state: State) -> None:
    with pytest.raises(ValueError):
        validate_transition(state, state)


def test_phase_one_blocks_approval_and_submission() -> None:
    with pytest.raises(ValueError, match="unavailable"):
        validate_transition(State.PENDING_APPROVAL, State.APPROVED)
    with pytest.raises(ValueError, match="unavailable"):
        validate_transition(State.APPROVED, State.SUBMITTING)
    validate_transition(State.DISCOVERED, State.MATCHED)
    with pytest.raises(ValueError):
        validate_transition(State.VERIFICATION_REQUIRED, State.SUBMITTING)


def test_profile_confirmation_validation() -> None:
    with pytest.raises(ValidationError):
        ProfileUpdate(name="Demo", confirmed=False)
    with pytest.raises(ValidationError):
        ProfileUpdate(name="Demo", confirmed=True, skills=["Python", "python"])
    with pytest.raises(ValidationError):
        ProfileUpdate(
            name="Demo",
            confirmed=True,
            experiences=[
                {
                    "employer": "Demo",
                    "title": "Engineer",
                    "start_date": "2024-01-01",
                    "end_date": "2020-01-01",
                }
            ],
        )


def test_settings_redact_secrets() -> None:
    settings = Settings(api_key="secret-value-that-is-at-least-32-characters")
    assert "secret-value" not in repr(settings)


def test_shared_pages_do_not_identify_vacancies() -> None:
    first = identity_keys(
        company="Acme",
        title="Engineer",
        description="",
        source_url="https://linkedin.com/posts/recruiter-many-jobs",
        application_url="https://example.com/careers",
    )
    assert first == []
    second = identity_keys(
        company="Acme",
        title="Engineer",
        description="",
        source_url="https://example.com/jobs?job=42",
    )
    assert len(second) == 1


def test_fingerprint_preserves_technology_punctuation() -> None:
    from app.domain.identity import fingerprint

    assert fingerprint("C++ Engineer") != fingerprint("C# Engineer")
    assert fingerprint("Python   engineer") == fingerprint("python engineer")
