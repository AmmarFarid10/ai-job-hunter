import json
import os
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from app.config import get_settings
from app.database import get_session
from app.integrations.google_identity import GoogleIdentityError, exchange_identity
from app.main import app
from app.models import GoogleLoginFlow


@pytest.fixture
def google_config(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-google-client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-google-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_google_signup_login_replay_and_no_automatic_email_link(
    client, monkeypatch, google_config
):
    async def identity(*args):
        return {"sub": "google-subject-one", "email": "owner@example.com", "name": "Google Owner"}

    monkeypatch.setattr("app.services.google_auth.exchange_identity", identity)
    start = await client.post(
        "/api/v1/auth/google/start", json={"mode": "signup", "setup_key": os.environ["API_KEY"]}
    )
    assert start.status_code == 200, start.text
    query = parse_qs(urlsplit(start.json()["authorization_url"]).query)
    assert query["scope"] == ["openid email profile"] and query["code_challenge_method"] == ["S256"]
    assert "state" in query and "nonce" in query
    async for session in app.dependency_overrides[get_session]():
        flow = await session.scalar(select(GoogleLoginFlow))
        assert flow.state_hash != start.json()["state"] and flow.verifier
    data = {"state": start.json()["state"], "code": "example-code"}
    completed = await client.post("/api/v1/auth/google/complete", json=data)
    assert completed.status_code == 200, completed.text
    assert completed.json()["user"]["google_connected"]
    assert (await client.post("/api/v1/auth/google/complete", json=data)).status_code == 400
    async for session in app.dependency_overrides[get_session]():
        flow = await session.scalar(select(GoogleLoginFlow))
        assert flow.consumed_at and not flow.verifier
    first = await client.post("/api/v1/auth/google/start", json={"mode": "login"})
    assert (
        await client.post(
            "/api/v1/auth/google/complete", json={"state": first.json()["state"], "code": "code"}
        )
    ).status_code == 200

    async def wrong_identity(*args):
        return {"sub": "different-google-subject", "email": "owner@example.com"}

    monkeypatch.setattr("app.services.google_auth.exchange_identity", wrong_identity)
    second = await client.post("/api/v1/auth/google/start", json={"mode": "login"})
    assert (
        await client.post(
            "/api/v1/auth/google/complete", json={"state": second.json()["state"], "code": "code"}
        )
    ).status_code == 403


async def test_google_link_requires_active_owner_session(client, monkeypatch, google_config):
    registered = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Owner",
            "email": "owner@example.com",
            "password": "fictional-password-12345",
            "setup_key": os.environ["API_KEY"],
        },
    )
    token = registered.json()["token"]
    assert (
        await client.post("/api/v1/auth/google/start", json={"mode": "link"})
    ).status_code == 401
    headers = {"X-Owner-Session": token}
    start = await client.post("/api/v1/auth/google/start", json={"mode": "link"}, headers=headers)
    assert start.status_code == 200

    async def identity(*args):
        return {"sub": "linked-google-subject", "email": "different@example.com"}

    monkeypatch.setattr("app.services.google_auth.exchange_identity", identity)
    result = await client.post(
        "/api/v1/auth/google/complete", json={"state": start.json()["state"], "code": "code"}
    )
    assert result.status_code == 200 and result.json()["user"]["email"] == "owner@example.com"
    other = await client.post("/api/v1/auth/google/start", json={"mode": "link"}, headers=headers)
    await client.post("/api/v1/auth/logout", headers=headers)
    assert (
        await client.post(
            "/api/v1/auth/google/complete", json={"state": other.json()["state"], "code": "code"}
        )
    ).status_code == 401


@pytest.mark.parametrize(
    "changed",
    [
        {},
        {"aud": "wrong-client"},
        {"iss": "https://evil.example"},
        {"nonce": "wrong-nonce"},
        {"email_verified": False},
        {"exp": 1},
    ],
)
async def test_google_id_token_signature_and_claim_validation(monkeypatch, google_config, changed):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": "test-google-client",
        "sub": "google-subject",
        "iat": now,
        "exp": now + 300,
        "nonce": "expected-nonce",
        "email": "owner@example.com",
        "email_verified": True,
    } | changed
    encoded = jwt.encode(claims, private, algorithm="RS256", headers={"kid": "test-key"})
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key())) | {
        "kid": "test-key",
        "alg": "RS256",
    }

    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"id_token": encoded})
        assert str(request.url) == "https://www.googleapis.com/oauth2/v3/certs"
        return httpx.Response(200, json={"keys": [jwk]})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    if changed:
        with pytest.raises(GoogleIdentityError):
            await exchange_identity(get_settings(), "code", "verifier", "expected-nonce")
    else:
        result = await exchange_identity(get_settings(), "code", "verifier", "expected-nonce")
        assert result["sub"] == "google-subject"


async def test_google_creates_distinct_users_and_link_cannot_take_over_another_user(
    client, monkeypatch, google_config
):
    claims = {"sub": "first-subject", "email": "first@example.com", "name": "First"}

    async def identity(*args):
        return dict(claims)

    monkeypatch.setattr("app.services.google_auth.exchange_identity", identity)

    async def complete(mode, headers=None):
        start = await client.post("/api/v1/auth/google/start", json={"mode": mode}, headers=headers)
        assert start.status_code == 200, start.text
        return await client.post(
            "/api/v1/auth/google/complete",
            json={"state": start.json()["state"], "code": "fake-code"},
        )

    first = await complete("signup")
    assert first.status_code == 200 and first.json()["user"]["role"] == "USER"
    h1 = {"X-API-Key": "", "X-Owner-Session": first.json()["token"]}
    claims.update(sub="second-subject", email="second@example.com", name="Second")
    second = await complete("signup")
    assert second.status_code == 200
    assert first.json()["user"]["id"] != second.json()["user"]["id"]
    # Logging in selects the verified subject, never the first account in the DB.
    logged = await complete("login")
    assert logged.json()["user"]["id"] == second.json()["user"]["id"]
    assert (await complete("link", h1)).status_code == 409
    claims.update(sub="unlinked-subject", email="first@example.com")
    assert (await complete("signup")).status_code == 409
    # Rate limiting a nonexistent password account must not block another user.
