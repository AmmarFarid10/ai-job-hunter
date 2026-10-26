import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit

from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.auth import session_hash
from app.integrations.google_identity import GoogleIdentityError, exchange_identity
from app.models import GoogleLoginFlow, LoginSession, WorkspaceAccount
from app.services.auth import current_session, issue_session, throttle


class GoogleStart(BaseModel):
    mode: Literal["signup", "login", "link"]
    setup_key: SecretStr | None = Field(default=None, max_length=500)


class GoogleComplete(BaseModel):
    state: str = Field(min_length=32, max_length=200)
    code: str = Field(min_length=1, max_length=4096)


def google_available() -> bool:
    settings = get_settings()
    return bool(settings.google_client_id and settings.google_client_secret)


async def start_google(
    session: AsyncSession, data: GoogleStart, owner_token: str | None
) -> tuple[int, dict[str, Any]]:
    if not google_available():
        return 503, {"detail": "Google sign-in is not configured"}
    if get_settings().environment != "production" and not await throttle(session):
        return 429, {"detail": "Too many attempts. Try again in a minute"}
    settings = get_settings()
    redirect = urlsplit(settings.google_redirect_uri)
    if (
        (
            redirect.scheme != "https"
            and not (redirect.scheme == "http" and redirect.hostname in {"localhost", "127.0.0.1"})
        )
        or redirect.fragment
        or redirect.username
    ):
        return 503, {"detail": "Invalid Google callback configuration"}
    linked_session = None
    if data.mode == "link":
        linked_session = await current_session(session, owner_token)
    state, nonce, verifier = (
        secrets.token_urlsafe(32),
        secrets.token_urlsafe(32),
        secrets.token_urlsafe(48),
    )
    flow = GoogleLoginFlow(
        state_hash=session_hash(state),
        nonce=nonce,
        verifier=verifier,
        mode=data.mode,
        account_id=linked_session.account_id if linked_session else None,
        login_session_id=linked_session.id if linked_session else None,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    session.add(flow)
    await session.flush()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return 200, {
        "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + query,
        "state": state,
    }


async def complete_google(
    session: AsyncSession, data: GoogleComplete
) -> tuple[int, dict[str, Any]]:
    if not google_available():
        return 503, {"detail": "Google sign-in is not configured"}
    flow = await session.scalar(
        select(GoogleLoginFlow)
        .where(GoogleLoginFlow.state_hash == session_hash(data.state))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if flow is None or flow.consumed_at or flow.expires_at <= datetime.now(UTC):
        return 400, {"detail": "Google sign-in expired or was already used. Start again"}
    flow.consumed_at = datetime.now(UTC)
    verifier, flow.verifier = (
        flow.verifier,
        "",
    )  # Remove short-lived exchange secret after consumption.
    try:
        claims = await exchange_identity(get_settings(), data.code, verifier, flow.nonce)
    except GoogleIdentityError:
        return 400, {"detail": "Google identity could not be verified. Start sign-in again"}
    # Serialize identities, not all sign-ins globally. Email matches still never auto-link.
    for identity in sorted({claims["sub"], claims["email"].casefold()}):
        lock_key = int.from_bytes(
            hashlib.sha256(identity.encode()).digest()[:8], "big", signed=True
        )
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    account = await session.scalar(
        select(WorkspaceAccount)
        .where(WorkspaceAccount.google_sub == claims["sub"])
        .with_for_update()
    )
    if flow.mode == "signup":
        if account is not None:
            if claims["email"].casefold() == account.email:
                account.email_verified_at = datetime.now(UTC)
            return 200, await issue_session(session, account)
        email = claims["email"].casefold()
        if len(email) > 320:
            return 400, {"detail": "Invalid Google identity"}
        if await session.scalar(select(WorkspaceAccount.id).where(WorkspaceAccount.email == email)):
            return 409, {"detail": "Sign in with your password, then connect Google in Settings"}
        account = WorkspaceAccount(
            name=str(claims.get("name") or "Workspace owner")[:200],
            email=email,
            password_hash="!google-only",
            google_sub=claims["sub"],
            email_verified_at=datetime.now(UTC),
        )
        session.add(account)
        await session.flush()
    elif flow.mode == "link":
        if account is not None and account.id != flow.account_id:
            return 409, {"detail": "Google account is already connected to another user"}
        account = await session.get(WorkspaceAccount, flow.account_id) if flow.account_id else None
        linked = (
            await session.get(LoginSession, flow.login_session_id)
            if flow.login_session_id
            else None
        )
        if (
            account is None
            or account.id != flow.account_id
            or linked is None
            or linked.revoked_at
            or linked.expires_at <= datetime.now(UTC)
        ):
            return 401, {"detail": "Sign in again before linking Google"}
        if account.google_sub and account.google_sub != claims["sub"]:
            return 409, {"detail": "A different Google account is already connected"}
        account.google_sub = claims["sub"]
        await session.flush()
    elif account is None or account.google_sub != claims["sub"]:
        return 403, {
            "detail": "Use password login first, then connect this Google account in Settings"
        }
    assert account is not None
    if claims["email"].casefold() == account.email:
        account.email_verified_at = datetime.now(UTC)
    return 200, await issue_session(session, account)
