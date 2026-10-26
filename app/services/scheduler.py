import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.matching import run_matching
from app.config import get_settings
from app.database import get_engine
from app.domain.matching import MatchingRequest
from app.integrations.matching.rules import RulesExtractor
from app.models import Job, NotificationSetting
from app.services.notifications import build_report, dispatch_report, report_slot

logger = logging.getLogger("jobhunter")


async def scheduled_reports() -> None:
    # One scheduler run across every worker/container; session lock survives commits below.
    async with get_engine().connect() as guard:
        acquired = await guard.scalar(text("SELECT pg_try_advisory_lock(710002002)"))
        await guard.commit()
        if not acquired:
            return
        try:
            await _scheduled_reports()
        finally:
            await guard.execute(text("SELECT pg_advisory_unlock(710002002)"))
            await guard.commit()


async def _scheduled_reports() -> None:
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory(info={"system": True}) as session:
        candidates = list(
            (
                await session.execute(
                    select(
                        NotificationSetting.candidate_id, NotificationSetting.owner_account_id
                    ).where(NotificationSetting.enabled.is_(True))
                )
            ).all()
        )
    slot = report_slot(datetime.now(UTC))
    for candidate_id, owner_id in candidates:
        try:
            if get_settings().require_email_verification:
                from app.models import WorkspaceAccount

                async with factory() as gate:
                    owner = await gate.get(WorkspaceAccount, owner_id) if owner_id else None
                    if owner is None or owner.email_verified_at is None:
                        continue
            async with factory(info={"owner_id": owner_id, "system": owner_id is None}) as session:
                # Refresh deterministic matches from already stored jobs; no external discovery.
                job_ids = list(
                    (
                        await session.scalars(
                            select(Job.id).order_by(Job.created_at.desc(), Job.id).limit(100)
                        )
                    ).all()
                )
                if job_ids:
                    await run_matching(
                        session,
                        MatchingRequest(
                            candidate_id=candidate_id,
                            job_ids=job_ids,
                            idempotency_key=f"report-{candidate_id}-{slot}",
                        ),
                        RulesExtractor(),
                        get_settings().matching_timeout_seconds,
                    )
                report = await build_report(session, candidate_id, slot, True)
                report_id = report.id
                await session.commit()
                await dispatch_report(session, report_id)
        except Exception:
            # Do not log exception bodies, recipients or report content.
            logger.error("Scheduled notification report failed")


def make_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ZoneInfo("Asia/Karachi"))
    scheduler.add_job(
        scheduled_reports,
        CronTrigger(hour="10,20", minute=0, timezone=ZoneInfo("Asia/Karachi")),
        id="twice-daily-reports",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=1800,
        replace_existing=True,
    )
    return scheduler
