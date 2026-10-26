import hashlib

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import JobIdentity


async def lock_identities(session: AsyncSession, keys: list[str]) -> None:
    # PostgreSQL advisory locks last until the surrounding transaction ends.
    for key in sorted(keys):
        lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})


async def find_identity_jobs(session: AsyncSession, keys: list[str]) -> set[object]:
    result = await session.scalars(select(JobIdentity.job_id).where(JobIdentity.key.in_(keys)))
    return set(result.all())
