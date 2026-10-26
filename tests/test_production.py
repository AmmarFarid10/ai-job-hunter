import asyncio
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_session
from app.main import app
from app.models import UsageCounter
from app.services.quotas import reserve_usage
from tests.test_workspaces import register

PRODUCTION = {
    "environment": "production",
    "require_email_verification": True,
    "smtp_host": "smtp.provider.test",
    "auth_sender_email": "no-reply@jobs.example.com",
    "allow_api_key_auth": False,
    "allow_admin_bootstrap": False,
    "gateway_token": "fictional-gateway-token-of-at-least-32-characters",
    "dashboard_url": "https://jobs.example.com",
    "database_url": "postgresql+asyncpg://app:private-fixture-password@db/jobhunter",
    "api_key": "fictional-maintenance-secret-of-at-least-32-characters",
    "google_client_id": None,
}


@pytest.mark.parametrize(
    "patch",
    [
        {"require_email_verification": False},
        {"smtp_host": None},
        {"gateway_token": None},
        {"allow_api_key_auth": True},
        {"allow_admin_bootstrap": True},
        {"dashboard_url": "http://jobs.example.com"},
        {"dashboard_url": "https://localhost"},
        {"database_url": "postgresql+asyncpg://jobhunter:localdev@db/jobhunter"},
        {
            "google_client_id": "qa-client",
            "google_client_secret": "private",
            "google_redirect_uri": "http://localhost/callback",
        },
    ],
)
def test_production_configuration_fails_closed(patch):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**PRODUCTION, **patch})


def test_valid_production_settings_hide_secrets():
    settings = Settings(_env_file=None, **PRODUCTION)
    assert settings.environment == "production"
    assert "private-fixture-password" not in repr(settings)
    assert "fictional-gateway-token" not in repr(settings)


async def test_gateway_required_and_api_key_disabled_in_production(client, monkeypatch):
    for key, value in PRODUCTION.items():
        if value is not None:
            monkeypatch.setenv(
                key.upper(), str(value).lower() if isinstance(value, bool) else value
            )
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    # Ignore local OAuth config in this test while preserving a valid callback origin.
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://jobs.example.com/api/oauth/google/callback")
    get_settings.cache_clear()
    assert (await client.get("/api/v1/auth/status")).status_code == 403
    gateway = {"X-Gateway-Token": PRODUCTION["gateway_token"], "X-Client-IP": "203.0.113.10"}
    result = await client.get("/api/v1/auth/status", headers=gateway)
    assert result.status_code == 200, result.text
    assert result.json()["admin_bootstrap_available"] is False
    assert (await client.get("/api/v1/candidates", headers=gateway)).status_code == 401
    assert (await client.get("/health")).status_code == 200


async def test_daily_budgets_are_atomic_and_separate_per_account(client, monkeypatch):
    one, h1 = await register(client, "budget-one@example.com")
    two, h2 = await register(client, "budget-two@example.com")
    monkeypatch.setenv("DAILY_DISCOVERY_LIMIT", "3")
    get_settings.cache_clear()
    async for session in app.dependency_overrides[get_session]():
        engine = session.bind

    async def reserve(account):
        async with AsyncSession(
            bind=engine, info={"owner_id": uuid.UUID(account["user"]["id"])}
        ) as worker:
            try:
                await reserve_usage(worker, "discovery")
                return 200
            except HTTPException as exc:
                return exc.status_code

    results = await asyncio.gather(*(reserve(one) for _ in range(12)))
    assert results.count(200) == 3 and results.count(429) == 9
    assert await reserve(two) == 200
    async for session in app.dependency_overrides[get_session]():
        assert sorted((await session.scalars(select(UsageCounter.used))).all()) == [1, 3]


async def test_replay_does_not_spend_another_discovery_budget(client, monkeypatch):
    _, headers = await register(client, "replay-budget@example.com")
    monkeypatch.setenv("DAILY_DISCOVERY_LIMIT", "1")
    get_settings.cache_clear()
    request = {"sources": ["mock"], "idempotency_key": "first-budget-key"}
    first = await client.post("/api/v1/discovery/runs", headers=headers, json=request)
    assert first.status_code == 201, first.text
    replay = await client.post("/api/v1/discovery/runs", headers=headers, json=request)
    assert replay.status_code == 201 and replay.json()["replayed"]
    second = await client.post(
        "/api/v1/discovery/runs",
        headers=headers,
        json={**request, "idempotency_key": "second-budget-key"},
    )
    assert second.status_code == 429, second.text


async def test_shared_budget_is_atomic_across_different_accounts(client, monkeypatch):
    users = [(await register(client, f"global-{i}@example.com"))[0] for i in range(4)]
    monkeypatch.setenv("GLOBAL_DAILY_DISCOVERY_LIMIT", "2")
    get_settings.cache_clear()
    async for session in app.dependency_overrides[get_session]():
        engine = session.bind

    async def reserve(account):
        async with AsyncSession(
            bind=engine, info={"owner_id": uuid.UUID(account["user"]["id"])}
        ) as worker:
            try:
                await reserve_usage(worker, "discovery")
                return 200
            except HTTPException as exc:
                return exc.status_code

    statuses = await asyncio.gather(*(reserve(account) for account in users))
    assert statuses.count(200) == 2 and statuses.count(429) == 2
    async for session in app.dependency_overrides[get_session]():
        from app.models import GlobalUsageCounter

        assert (
            await session.scalar(
                select(GlobalUsageCounter.used).where(GlobalUsageCounter.action == "discovery-day")
            )
            == 2
        )
        assert sum((await session.scalars(select(UsageCounter.used))).all()) == 2


async def test_candidate_creation_race_cannot_exceed_profile_cap(client, monkeypatch):
    _, headers = await register(client, "profile-cap@example.com")
    monkeypatch.setenv("MAX_CANDIDATES_PER_USER", "1")
    get_settings.cache_clear()
    responses = await asyncio.gather(
        *(
            client.post("/api/v1/candidates", headers=headers, json={"name": f"Profile {i}"})
            for i in range(4)
        )
    )
    assert sorted(response.status_code for response in responses) == [201, 429, 429, 429]
    assert len((await client.get("/api/v1/candidates", headers=headers)).json()) == 1


async def test_equal_job_text_does_not_merge_distinct_vacancies(client):
    from tests.test_api import JOB

    first = await client.post("/api/v1/jobs", json=JOB)
    second = await client.post(
        "/api/v1/jobs",
        json={
            **JOB,
            "employer_job_id": "different-id",
            "source_url": "https://example.com/jobs/different-id",
            "application_url": "https://example.com/jobs/different-id/apply",
        },
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["job"]["id"] != second.json()["job"]["id"]
    assert first.json()["job"]["id"] in second.json()["possible_duplicate_ids"]


@pytest.mark.parametrize("value", ["-1", "1000001", "999999999999999999999999999999999999"])
async def test_pagination_bounds_reject_oversized_values_without_database_errors(client, value):
    assert (await client.get("/api/v1/jobs?offset=" + value)).status_code == 422
    assert (await client.get("/api/v1/discovery/items?offset=" + value)).status_code == 422


async def test_malformed_json_and_negative_body_length_are_client_errors(client):
    response = await client.post(
        "/api/v1/candidates",
        content=b"[" * 1500 + b"]" * 1500,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code in {400, 422}, response.text
    malformed = await client.post(
        "/api/v1/candidates", content=b"{", headers={"Content-Type": "application/json"}
    )
    assert malformed.status_code == 400
    response = await client.post(
        "/api/v1/candidates",
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": "-1"},
    )
    assert response.status_code == 400, response.text
    response = await client.post(
        "/api/v1/jobs",
        content=b'"' + b"x" * (2 * 1024 * 1024) + b'"',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


async def test_google_only_accounts_cannot_use_fallback_password(client):
    from app.models import WorkspaceAccount

    async for session in app.dependency_overrides[get_session]():
        session.add(
            WorkspaceAccount(
                name="Google Only",
                email="google-only@example.com",
                password_hash="!google-only",
                google_sub="fictional-google-only-sub",
            )
        )
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "google-only@example.com", "password": "unusable-fallback-password"},
    )
    assert response.status_code == 401
    assert (
        await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "blank@example.com",
                "name": "   ",
                "password": "fictional-blank-name-password",
            },
        )
    ).status_code == 422
