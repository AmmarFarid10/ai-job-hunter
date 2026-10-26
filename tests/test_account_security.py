import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.database import get_session
from app.domain.auth import session_hash
from app.integrations.auth_mail import AuthMailError
from app.main import app
from app.models import AccountActionToken, AccountSecurityEvent


@pytest.fixture
def mailbox(monkeypatch):
    messages = []

    async def deliver(settings, recipient, purpose, link):
        messages.append((recipient, purpose, parse_qs(urlsplit(link).fragment)[purpose][0]))

    monkeypatch.setattr("app.services.account_security.send_auth_email", deliver)
    monkeypatch.setenv("REQUIRE_EMAIL_VERIFICATION", "true")
    get_settings.cache_clear()
    return messages


async def register(client, email="verified@example.com"):
    response = await client.post(
        "/api/v1/auth/signup",
        json={"name": "QA User", "email": email, "password": "fictional-original-password"},
    )
    assert response.status_code == 201, response.text
    return response.json(), {"X-API-Key": "", "X-Owner-Session": response.json()["token"]}


async def test_verification_is_required_and_one_use_without_changing_candidate_facts(
    client, mailbox
):
    account, headers = await register(client)
    assert account["user"]["email_verified"] is False
    assert (await client.get("/api/v1/candidates", headers=headers)).status_code == 403
    raw = mailbox[0][2]
    async for session in app.dependency_overrides[get_session]():
        stored = await session.scalar(select(AccountActionToken))
        assert stored.token_hash == session_hash(raw) and stored.token_hash != raw
    response = await client.post("/api/v1/auth/verify-email", json={"token": raw})
    assert response.status_code == 200, response.text
    assert (await client.get("/api/v1/candidates", headers=headers)).json() == []
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["user"]["email_verified"]
    assert (await client.post("/api/v1/auth/verify-email", json={"token": raw})).status_code == 400
    assert (
        await client.post(
            "/api/v1/auth/reset-password", json={"token": raw, "password": "fictional-new-password"}
        )
    ).status_code == 400


async def test_password_reset_generic_response_revokes_all_sessions_and_rejects_replay(
    client, mailbox
):
    account, headers = await register(client)
    verify = mailbox[0][2]
    await client.post("/api/v1/auth/verify-email", json={"token": verify})
    second = await client.post(
        "/api/v1/auth/login",
        json={"email": account["user"]["email"], "password": "fictional-original-password"},
    )
    known = await client.post(
        "/api/v1/auth/request-password-reset", json={"email": account["user"]["email"]}
    )
    unknown = await client.post(
        "/api/v1/auth/request-password-reset", json={"email": "missing@example.com"}
    )
    assert known.status_code == unknown.status_code == 202 and known.json() == unknown.json()
    raw = next(message[2] for message in mailbox if message[1] == "reset")
    assert raw not in known.text
    result = await client.post(
        "/api/v1/auth/reset-password", json={"token": raw, "password": "fictional-updated-password"}
    )
    assert result.status_code == 200, result.text
    for token in (account["token"], second.json()["token"]):
        assert (
            await client.get("/api/v1/auth/me", headers={"X-Owner-Session": token})
        ).status_code == 401
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={"email": account["user"]["email"], "password": "fictional-original-password"},
        )
    ).status_code == 401
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={"email": account["user"]["email"], "password": "fictional-updated-password"},
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/auth/reset-password",
            json={"token": raw, "password": "fictional-another-password"},
        )
    ).status_code == 400
    async for session in app.dependency_overrides[get_session]():
        actions = set((await session.scalars(select(AccountSecurityEvent.action))).all())
        assert {"EMAIL_VERIFIED", "PASSWORD_RESET", "RESET_REQUESTED"}.issubset(actions)


async def test_expired_reissued_and_parallel_verification_links(client, mailbox):
    account, headers = await register(client)
    old = mailbox[0][2]
    async for session in app.dependency_overrides[get_session]():
        row = await session.scalar(select(AccountActionToken))
        row.created_at = datetime.now(UTC) - timedelta(minutes=2)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert (await client.post("/api/v1/auth/verify-email", json={"token": old})).status_code == 400
    await client.post("/api/v1/auth/request-verification", json={"email": account["user"]["email"]})
    new = mailbox[-1][2]
    assert new != old
    responses = await asyncio.gather(
        *(client.post("/api/v1/auth/verify-email", json={"token": new}) for _ in range(2))
    )
    assert sorted(response.status_code for response in responses) == [200, 400]
    assert (await client.post("/api/v1/auth/verify-email", json={"token": old})).status_code == 400


async def test_mail_cooldown_failure_invalidates_tokens_and_hides_errors(
    client, mailbox, monkeypatch
):
    account, _ = await register(client)
    await client.post("/api/v1/auth/request-verification", json={"email": account["user"]["email"]})
    assert len(mailbox) == 1

    async def fail(*args):
        raise AuthMailError("private-server-error-must-not-leak")

    monkeypatch.setattr("app.services.account_security.send_auth_email", fail)
    result = await client.post(
        "/api/v1/auth/request-password-reset", json={"email": account["user"]["email"]}
    )
    assert result.status_code == 202 and "private-server" not in result.text
    async for session in app.dependency_overrides[get_session]():
        row = await session.scalar(
            select(AccountActionToken).where(AccountActionToken.purpose == "reset")
        )
        assert row.consumed_at is not None
        assert await session.scalar(
            select(AccountSecurityEvent.id).where(AccountSecurityEvent.action == "AUTH_MAIL_FAILED")
        )


async def test_invalid_credentials_are_not_echoed_by_validation(client):
    secret = "short-secret"
    response = await client.post(
        "/api/v1/auth/signup", json={"name": "QA", "email": "invalid", "password": secret}
    )
    assert response.status_code == 422 and secret not in response.text
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": "x" * 201})
    ).status_code == 422


async def test_global_auth_mail_budget_does_not_disable_existing_verification_link(
    client, mailbox, monkeypatch
):
    monkeypatch.setenv("DAILY_AUTH_MAIL_LIMIT", "1")
    get_settings.cache_clear()
    first, _ = await register(client, "one-mail@example.com")
    first_token = mailbox[0][2]
    second, _ = await register(client, "two-mail@example.com")
    assert len(mailbox) == 1
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": first_token})
    ).status_code == 200
    async for session in app.dependency_overrides[get_session]():
        assert await session.scalar(
            select(AccountSecurityEvent.id).where(
                AccountSecurityEvent.action == "AUTH_MAIL_BUDGET_EXHAUSTED"
            )
        )


async def test_parallel_password_reset_uses_token_once(client, mailbox):
    account, _ = await register(client)
    await client.post(
        "/api/v1/auth/request-password-reset", json={"email": account["user"]["email"]}
    )
    raw = next(message[2] for message in mailbox if message[1] == "reset")
    replies = await asyncio.gather(
        *(
            client.post(
                "/api/v1/auth/reset-password",
                json={"token": raw, "password": "fictional-parallel-reset-password"},
            )
            for _ in range(2)
        )
    )
    assert sorted(response.status_code for response in replies) == [200, 400]
