import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.domain.auth import password_hash, session_hash
from app.integrations.auth_mail import AuthMailError, send_auth_email
from app.models import AccountActionToken, AccountSecurityEvent, LoginSession, WorkspaceAccount
from app.services.auth import throttle


async def send_action(
    session: AsyncSession,
    email: str,
    purpose: Literal["verify", "reset"],
    background: BackgroundTasks,
) -> None:
    # Generic response regardless of account existence, verification, throttling or transport.
    if not await throttle(session, f"mail:{purpose}:{email}"):
        return
    account = await session.scalar(
        select(WorkspaceAccount).where(WorkspaceAccount.email == email).with_for_update()
    )
    if account is None or account.password_hash == "!bootstrap":
        return
    if purpose == "verify" and account.email_verified_at:
        return
    now = datetime.now(UTC)
    last = await session.scalar(
        select(AccountActionToken.created_at)
        .where(
            AccountActionToken.account_id == account.id,
            AccountActionToken.purpose == purpose,
            AccountActionToken.created_at > now - timedelta(minutes=1),
        )
        .limit(1)
    )
    if last:
        return
    from app.models import GlobalUsageCounter

    budget = insert(GlobalUsageCounter).values(action="auth-mail-day", bucket=now.date(), used=1)
    reservation = budget.on_conflict_do_update(
        index_elements=["action", "bucket"],
        set_={"used": GlobalUsageCounter.used + 1},
        where=GlobalUsageCounter.used < get_settings().daily_auth_mail_limit,
    ).returning(GlobalUsageCounter.used)
    if await session.scalar(reservation) is None:
        session.add(
            AccountSecurityEvent(account_id=account.id, action="AUTH_MAIL_BUDGET_EXHAUSTED")
        )
        return
    # Reissuing invalidates previous links; tokens are bound to one account and purpose.
    await session.execute(
        update(AccountActionToken)
        .where(
            AccountActionToken.account_id == account.id,
            AccountActionToken.purpose == purpose,
            AccountActionToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    raw = secrets.token_urlsafe(32)
    token = AccountActionToken(
        account_id=account.id,
        token_hash=session_hash(raw),
        purpose=purpose,
        expires_at=now + timedelta(minutes=60 if purpose == "verify" else 15),
    )
    session.add(token)
    session.add(AccountSecurityEvent(account_id=account.id, action=f"{purpose.upper()}_REQUESTED"))
    await session.flush()
    token_id, recipient = token.id, account.email
    # Persist before external delivery so crashes cannot send a link which was rolled back.
    await session.commit()
    link = get_settings().dashboard_url.rstrip("/") + f"/#{purpose}={raw}"
    background.add_task(
        deliver_action, session.bind, token_id, token.account_id, recipient, purpose, link
    )


async def deliver_action(
    bind: AsyncEngine | AsyncConnection | None,
    token_id: uuid.UUID,
    account_id: uuid.UUID,
    recipient: str,
    purpose: str,
    link: str,
) -> None:
    try:
        await send_auth_email(get_settings(), recipient, purpose, link)
    except AuthMailError:
        # Reject possibly delivered links on failure; retries require a fresh user request.
        async with AsyncSession(bind=bind, expire_on_commit=False) as worker:
            async with worker.begin():
                row = await worker.get(AccountActionToken, token_id)
                if row:
                    row.consumed_at = datetime.now(UTC)
                worker.add(AccountSecurityEvent(account_id=account_id, action="AUTH_MAIL_FAILED"))


async def consume_action(
    session: AsyncSession,
    raw: str,
    purpose: Literal["verify", "reset"],
    password: str | None = None,
) -> None:
    # Account lock first establishes one lock order with sending/reissuing and parallel resets.
    account_id = await session.scalar(
        select(AccountActionToken.account_id).where(
            AccountActionToken.token_hash == session_hash(raw),
            AccountActionToken.purpose == purpose,
        )
    )
    if not account_id:
        raise HTTPException(400, "Link expired or invalid. Request a new link")
    account = await session.scalar(
        select(WorkspaceAccount).where(WorkspaceAccount.id == account_id).with_for_update()
    )
    row = await session.scalar(
        select(AccountActionToken)
        .where(
            AccountActionToken.token_hash == session_hash(raw),
            AccountActionToken.purpose == purpose,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    now = datetime.now(UTC)
    if account is None or row is None or row.consumed_at or row.expires_at <= now:
        raise HTTPException(400, "Link expired or invalid. Request a new link")
    row.consumed_at = now
    if purpose == "verify":
        account.email_verified_at = now
    else:
        assert password is not None
        account.password_hash = await run_in_threadpool(password_hash, password)
        # Verification/reset do not silently sign a user in. Reset revokes every session.
        await session.execute(
            update(LoginSession)
            .where(LoginSession.account_id == account.id, LoginSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.execute(
            update(AccountActionToken)
            .where(
                AccountActionToken.account_id == account.id,
                AccountActionToken.purpose == "reset",
                AccountActionToken.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
    session.add(
        AccountSecurityEvent(
            account_id=account.id,
            action="EMAIL_VERIFIED" if purpose == "verify" else "PASSWORD_RESET",
        )
    )
    await session.flush()
