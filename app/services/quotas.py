"""Atomic, persisted budgets shared by every backend worker; failed work also consumes budget."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import GlobalUsageCounter, UsageCounter


async def reserve_usage(session: AsyncSession, action: str) -> None:
    if session.info.get("system"):
        return
    actor = session.info.get("actor_id") or session.info.get("owner_id")
    if not actor:
        raise HTTPException(403, "Workspace context required")
    settings = get_settings()
    limits = {
        "discovery": settings.daily_discovery_limit,
        "generation": settings.daily_generation_limit,
        "upload": settings.daily_upload_limit,
        "matching": settings.daily_matching_limit,
        "report": settings.daily_report_limit,
    }
    limit = limits[action]
    statement = insert(UsageCounter).values(
        account_id=actor, action=action, day=datetime.now(UTC).date(), used=1
    )
    reservation = statement.on_conflict_do_update(
        index_elements=["account_id", "action", "day"],
        set_={"used": UsageCounter.used + 1},
        where=UsageCounter.used < limit,
    ).returning(UsageCounter.used)
    async with AsyncSession(bind=session.bind) as worker:
        async with worker.begin():
            used = await worker.scalar(reservation)
            if used is None:
                raise HTTPException(
                    429,
                    "Daily usage limit reached. Try again tomorrow",
                    headers={"Retry-After": "86400"},
                )
            if action == "discovery":
                day = datetime.now(UTC).date()
                for name, bucket, cap in (
                    ("discovery-day", day, settings.global_daily_discovery_limit),
                    (
                        "discovery-month",
                        day.replace(day=1),
                        settings.global_monthly_discovery_limit,
                    ),
                ):
                    global_statement = insert(GlobalUsageCounter).values(
                        action=name, bucket=bucket, used=1
                    )
                    global_reservation = global_statement.on_conflict_do_update(
                        index_elements=["action", "bucket"],
                        set_={"used": GlobalUsageCounter.used + 1},
                        where=GlobalUsageCounter.used < cap,
                    ).returning(GlobalUsageCounter.used)
                    if await worker.scalar(global_reservation) is None:
                        raise HTTPException(
                            429,
                            "Shared discovery budget reached. Try again later",
                            headers={"Retry-After": "86400"},
                        )
    if used is None:
        raise HTTPException(
            429, "Daily usage limit reached. Try again tomorrow", headers={"Retry-After": "86400"}
        )
