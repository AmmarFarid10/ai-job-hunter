import hashlib

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def try_run_lock(session: AsyncSession, idempotency_key: str) -> None:
    key = int.from_bytes(
        hashlib.sha256(("discovery:" + idempotency_key).encode()).digest()[:8], "big", signed=True
    )
    acquired = await session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key})
    if not acquired:
        raise HTTPException(409, "A discovery run with this key is already in progress")
