import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.domain.auth import Credentials, Signup, password_hash, password_valid, session_hash
from app.models import AccountSecurityEvent, AuthThrottle, LoginSession, WorkspaceAccount

# Fixed-cost fallback when no account exists; never a usable stored password.
DUMMY_HASH = password_hash("unusable-fallback-password", b"0" * 16)


def throttle_key(identity: str) -> str:
    return hashlib.sha256(("auth:" + identity).encode()).hexdigest()[:30]


async def throttle(session: AsyncSession, identity: str | None = None, limit: int = 10) -> bool:
    key = throttle_key(identity) if identity else "workspace-auth"
    now = datetime.now(UTC)
    await session.execute(
        insert(AuthThrottle)
        .values(key=key, window_start=now, attempts=0)
        .on_conflict_do_nothing(index_elements=["key"])
    )
    row = await session.scalar(
        select(AuthThrottle)
        .where(AuthThrottle.key == key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None
    if now - row.window_start >= timedelta(minutes=1):
        row.window_start, row.attempts = now, 0
    if row.attempts >= limit:
        return False
    row.attempts += 1
    return True


def account_view(account: WorkspaceAccount) -> dict[str, Any]:
    return {
        "id": account.id,
        "role": account.role,
        "name": account.name,
        "email": account.email,
        "email_verified": account.email_verified_at is not None,
        "google_connected": account.google_sub is not None,
    }


async def issue_session(session: AsyncSession, account: WorkspaceAccount) -> dict[str, Any]:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(hours=8)
    session.add(
        LoginSession(account_id=account.id, token_hash=session_hash(token), expires_at=expires)
    )
    session.add(AccountSecurityEvent(account_id=account.id, action="SESSION_CREATED"))
    await session.flush()
    return {"user": account_view(account), "token": token, "expires_at": expires}


async def signup(session: AsyncSession, data: Signup) -> tuple[int, dict[str, Any]]:
    if not await throttle(session, data.email):
        return 429, {"detail": "Too many attempts. Try again in a minute"}
    if await session.scalar(
        select(WorkspaceAccount.id).where(WorkspaceAccount.email == data.email)
    ):
        return 409, {"detail": "Unable to create account. Try signing in instead"}
    account = WorkspaceAccount(
        name=data.name,
        email=data.email,
        password_hash=await run_in_threadpool(password_hash, data.password.get_secret_value()),
    )
    session.add(account)
    await session.flush()
    return 201, await issue_session(session, account)


async def login(session: AsyncSession, data: Credentials) -> tuple[int, dict[str, Any]]:
    if not await throttle(session, data.email):
        return 429, {"detail": "Too many attempts. Try again in a minute"}
    account = await session.scalar(
        select(WorkspaceAccount).where(WorkspaceAccount.email == data.email).with_for_update()
    )
    password_account = account is not None and account.password_hash.startswith("scrypt-v1$")
    valid = await run_in_threadpool(
        password_valid,
        data.password.get_secret_value(),
        account.password_hash if account and password_account else DUMMY_HASH,
    )
    if account is None or not password_account or not valid:
        return 401, {"detail": "Invalid email or password"}
    return 200, await issue_session(session, account)


async def current_session(session: AsyncSession, token: str | None) -> LoginSession:
    if not token or len(token) > 200:
        raise HTTPException(401, "Sign in required")
    row = await session.scalar(
        select(LoginSession).where(
            LoginSession.token_hash == session_hash(token),
            LoginSession.revoked_at.is_(None),
            LoginSession.expires_at > datetime.now(UTC),
        )
    )
    if row is None:
        raise HTTPException(401, "Session expired or invalid. Sign in again")
    return row
