import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import get_engine
from app.models import Candidate
from app.schemas import JobCreate
from app.services.jobs import create_job


async def seed() -> None:
    engine = get_engine()
    try:
        async with async_sessionmaker(engine, info={"system": True})() as session, session.begin():
            existing = await session.scalar(
                select(Candidate).where(Candidate.name == "DEMO — fictional unverified candidate")
            )
            if existing is None:
                session.add(Candidate(name="DEMO — fictional unverified candidate", verified=False))
            await create_job(
                session,
                JobCreate(
                    title="Senior Python Engineer (sample)",
                    company="Fictional Demo Employer",
                    description="Development fixture only. Python APIs. Eligibility unknown.",
                    source_name="mock",
                    source_url="https://example.invalid/jobs/demo-001",
                    employer_job_id="demo-001",
                ),
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
