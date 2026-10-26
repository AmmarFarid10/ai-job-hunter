import asyncio
import os
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from app.database import get_session
from app.domain.auth import password_hash, password_valid, session_hash
from app.main import app
from app.models import AuthThrottle, LoginSession, WorkspaceAccount
from app.services.auth import throttle_key


def registration() -> dict:
    return {
        "name": "Workspace Owner",
        "email": "OWNER@example.com",
        "password": "fictional-password-12345",
        "setup_key": os.environ["API_KEY"],
    }


async def test_signup_login_and_revocable_sessions(client: AsyncClient):
    assert (await client.get("/api/v1/auth/status")).json()["signup_available"]
    result = await client.post("/api/v1/auth/signup", json=registration())
    assert result.status_code == 201, result.text
    token = result.json()["token"]
    assert result.json()["user"]["email"] == "owner@example.com"
    assert "password" not in result.text and "setup_key" not in result.text
    assert (await client.get("/api/v1/auth/status")).json()["signup_available"]
    assert (await client.post("/api/v1/auth/signup", json=registration())).status_code == 409
    headers = {"X-API-Key": "", "X-Owner-Session": token}
    assert (await client.get("/api/v1/candidates", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["user"][
        "name"
    ] == "Workspace Owner"
    async for session in app.dependency_overrides[get_session]():
        account = await session.scalar(select(WorkspaceAccount))
        stored = await session.scalar(select(LoginSession))
        assert (
            account.password_hash.startswith("scrypt-v1$")
            and registration()["password"] not in account.password_hash
        )
        assert stored.token_hash == session_hash(token) and token != stored.token_hash
    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/candidates", headers=headers)).status_code == 401
    logged = await client.post(
        "/api/v1/auth/login",
        json={"email": "OWNER@example.com", "password": registration()["password"]},
    )
    assert logged.status_code == 200 and logged.json()["token"] != token


async def test_public_signup_password_validation_and_duplicate_race(client: AsyncClient):
    assert (
        await client.post("/api/v1/auth/signup", json={**registration(), "password": "short"})
    ).status_code == 422
    assert (await client.get("/api/v1/auth/status")).json()["signup_available"]
    responses = await asyncio.gather(
        *(client.post("/api/v1/auth/signup", json=registration()) for _ in range(2))
    )
    assert sorted(r.status_code for r in responses) == [201, 409]


async def test_login_rate_limit_persists_and_errors_do_not_enumerate(client: AsyncClient):
    await client.post("/api/v1/auth/signup", json=registration())
    creds = {"email": "missing@example.com", "password": "wrong-password-12345"}
    missing = await client.post("/api/v1/auth/login", json=creds)
    wrong = await client.post("/api/v1/auth/login", json={**creds, "email": "owner@example.com"})
    assert missing.status_code == wrong.status_code == 401 and missing.json() == wrong.json()
    for _ in range(9):
        assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 401
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 429
    async for session in app.dependency_overrides[get_session]():
        row = await session.get(AuthThrottle, throttle_key("missing@example.com"))
        row.window_start = datetime.now(UTC) - timedelta(minutes=2)
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 401


async def test_expired_and_forged_session_rejected(client: AsyncClient):
    token = (await client.post("/api/v1/auth/signup", json=registration())).json()["token"]
    async for session in app.dependency_overrides[get_session]():
        row = await session.scalar(select(LoginSession))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert (
        await client.get("/api/v1/auth/me", headers={"X-Owner-Session": token})
    ).status_code == 401
    assert (
        await client.get(
            "/api/v1/candidates", headers={"X-API-Key": "", "X-Owner-Session": "forged"}
        )
    ).status_code == 401


def test_password_hashes_are_salted_and_do_not_accept_changes():
    first = password_hash("long-password-demo")
    assert first != password_hash("long-password-demo")
    assert password_valid("long-password-demo", first)
    assert not password_valid("wrong-password", first)
    assert not password_valid("long-password-demo", "malformed")
