"""Initialize the designated administrator from server-side configuration.

Run explicitly with `python -m app.admin`. Never reset an existing account password.
"""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.database import get_engine
from app.domain.auth import password_hash
from app.models import AdminAudit, WorkspaceAccount


async def initialize() -> None:
    settings = get_settings()
    if not settings.admin_email or not settings.admin_password:
        raise RuntimeError("Configure ADMIN_EMAIL and ADMIN_PASSWORD before initialization")
    email = settings.admin_email.casefold()
    engine = get_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            async with session.begin():
                await session.execute(text("SELECT pg_advisory_xact_lock(710002001)"))
                account = await session.scalar(
                    select(WorkspaceAccount).where(WorkspaceAccount.email == email)
                )
                if account is not None:
                    if account.role != "ADMIN":
                        raise RuntimeError(
                            "Account exists; use authenticated administrator setup to promote it"
                        )
                    print("Administrator already initialized; credentials unchanged")
                    return
                existing = await session.scalar(
                    select(WorkspaceAccount.id).where(
                        WorkspaceAccount.role == "ADMIN",
                        WorkspaceAccount.password_hash != "!bootstrap",
                    )
                )
                if existing:
                    raise RuntimeError("Administrator already configured; no account was created")
                account = WorkspaceAccount(
                    name="Administrator",
                    email=email,
                    role="ADMIN",
                    email_verified_at=datetime.now(UTC),
                    password_hash=await run_in_threadpool(
                        password_hash, settings.admin_password.get_secret_value()
                    ),
                )
                session.add(account)
                await session.flush()
                session.add(
                    AdminAudit(
                        actor_account_id=account.id,
                        target_account_id=account.id,
                        method="SETUP",
                        resource="administrator-initialization",
                    )
                )
            print("Administrator initialized successfully; credentials withheld")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(initialize())
