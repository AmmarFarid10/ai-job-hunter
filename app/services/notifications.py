import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.approvals import NotificationPreferences
from app.integrations.notifications.providers import DeliveryError, send_report
from app.models import (
    ApprovalRequest,
    Candidate,
    Job,
    JobMatch,
    JobSource,
    NotificationDelivery,
    NotificationReport,
    NotificationSetting,
    ResumeVersion,
)
from app.repositories.common import require
from app.services.discovery import request_hash
from app.services.matching import match_view


def report_slot(now: datetime) -> str:
    local = now.astimezone(ZoneInfo("Asia/Karachi"))
    return f"{local.date()}:{'20' if local.hour >= 20 else '10'}"


async def settings_view(session: AsyncSession, candidate_id: uuid.UUID) -> dict[str, Any]:
    await require(session, Candidate, candidate_id)
    row = await session.scalar(
        select(NotificationSetting).where(NotificationSetting.candidate_id == candidate_id)
    )
    values = (
        {
            key: getattr(row, key)
            for key in [
                "enabled",
                "email_enabled",
                "whatsapp_enabled",
                "email",
                "whatsapp_number",
                "consented_at",
            ]
        }
        if row
        else {
            "enabled": False,
            "email_enabled": True,
            "whatsapp_enabled": True,
            "email": None,
            "whatsapp_number": None,
            "consented_at": None,
        }
    )
    return values | {
        "mode": get_settings().notification_mode,
        "schedule": ["10:00", "20:00"],
        "timezone": "Asia/Karachi",
        "scheduler_enabled": get_settings().scheduler_enabled,
    }


async def save_settings(
    session: AsyncSession, candidate_id: uuid.UUID, data: NotificationPreferences
) -> dict[str, Any]:
    await require(session, Candidate, candidate_id, lock=True)
    if data.enabled and (not data.consent or not (data.email_enabled or data.whatsapp_enabled)):
        raise HTTPException(422, "Enabling reports requires consent and at least one channel")
    if data.enabled and get_settings().notification_mode == "live":
        if (
            data.email_enabled
            and not data.email
            or data.whatsapp_enabled
            and not data.whatsapp_number
        ):
            raise HTTPException(422, "Set a recipient for every enabled live channel")
    row = await session.scalar(
        select(NotificationSetting).where(NotificationSetting.candidate_id == candidate_id)
    )
    if row is None:
        row = NotificationSetting(candidate_id=candidate_id)
        session.add(row)
    for key, value in data.model_dump(exclude={"consent"}).items():
        setattr(row, key, value)
    row.consented_at = datetime.now(UTC) if data.enabled and data.consent else None
    await session.flush()
    return await settings_view(session, candidate_id)


async def build_report(
    session: AsyncSession, candidate_id: uuid.UUID, slot: str, deliver: bool
) -> NotificationReport:
    await require(session, Candidate, candidate_id, lock=True)
    existing = await session.scalar(
        select(NotificationReport).where(
            NotificationReport.candidate_id == candidate_id, NotificationReport.slot == slot
        )
    )
    if existing:
        if (existing.status == "PREVIEW") == deliver:
            raise HTTPException(409, "Report delivery choice changed; use a new request key")
        return existing
    settings = get_settings()
    preferences = await settings_view(session, candidate_id)
    if deliver and settings.notification_mode == "live" and not preferences["enabled"]:
        raise HTTPException(409, "Enable consented notification settings before live delivery")
    rows = (
        await session.scalars(
            select(JobMatch)
            .where(
                JobMatch.candidate_id == candidate_id,
                JobMatch.score >= JobMatch.threshold,
                JobMatch.decision.in_(["QUALIFIED", "REVIEW_REQUIRED"]),
            )
            .order_by(JobMatch.score.desc(), JobMatch.job_id)
            .limit(100)
        )
    ).all()
    items: list[dict[str, Any]] = []
    for match in rows:
        view = await match_view(session, match)
        if view["stale"]:
            continue
        version = await session.scalar(
            select(ResumeVersion)
            .where(ResumeVersion.candidate_id == candidate_id, ResumeVersion.job_id == match.job_id)
            .order_by(ResumeVersion.version.desc())
            .limit(1)
        )
        approval = await session.scalar(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.candidate_id == candidate_id, ApprovalRequest.job_id == match.job_id
            )
            .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
            .limit(1)
        )
        if (
            approval
            and approval.status != "PENDING"
            and (version is None or approval.resume_version_id == version.id)
        ):
            continue
        job = await require(session, Job, match.job_id)
        sources = list(
            (
                await session.scalars(
                    select(JobSource.url).where(JobSource.job_id == job.id).order_by(JobSource.id)
                )
            ).all()
        )
        fingerprint = (
            version.content_hash
            if version
            else request_hash({"match": match.requirements_hash, "job": match.job_hash})
        )
        items.append(
            {
                "job_id": str(job.id),
                "title": job.title,
                "company": job.company,
                "score": match.score,
                "decision": match.decision,
                "source_links": sources,
                "resume_version_id": str(version.id) if version else None,
                "resume_links": {
                    fmt: f"/api/v1/resumes/versions/{version.id}/download/{fmt}"
                    for fmt in ["pdf", "docx"]
                }
                if version
                else {},
                "approval_id": str(approval.id) if approval else None,
                "review_url": f"{settings.dashboard_url}/?candidate={candidate_id}&job={job.id}",
                "fingerprint": fingerprint,
            }
        )
    report = NotificationReport(
        candidate_id=candidate_id,
        slot=slot,
        mode=settings.notification_mode,
        content={"items": items, "timezone": "Asia/Karachi"},
        status="PREVIEW" if not deliver else "QUEUED",
    )
    session.add(report)
    await session.flush()
    if deliver:
        for channel in ["email", "whatsapp"]:
            if not preferences[f"{channel}_enabled"]:
                continue
            for item in items:
                key = request_hash(
                    {
                        "candidate": str(candidate_id),
                        "job": item["job_id"],
                        "fingerprint": item["fingerprint"],
                        "channel": channel,
                        "mode": settings.notification_mode,
                    }
                )
                if await session.scalar(
                    select(NotificationDelivery.id).where(
                        NotificationDelivery.deduplication_key == key
                    )
                ):
                    continue
                session.add(
                    NotificationDelivery(
                        candidate_id=candidate_id,
                        job_id=uuid.UUID(item["job_id"]),
                        channel=channel,
                        report_id=report.id,
                        deduplication_key=key,
                        status="PENDING",
                    )
                )
        await session.flush()
    return report


async def report_view(session: AsyncSession, report: NotificationReport) -> dict[str, Any]:
    deliveries = (
        await session.scalars(
            select(NotificationDelivery)
            .where(NotificationDelivery.report_id == report.id)
            .order_by(NotificationDelivery.created_at, NotificationDelivery.id)
        )
    ).all()
    return {
        "id": report.id,
        "candidate_id": report.candidate_id,
        "slot": report.slot,
        "mode": report.mode,
        "status": report.status,
        "created_at": report.created_at,
        "content": report.content,
        "deliveries": [
            {
                key: getattr(row, key)
                for key in ["id", "job_id", "channel", "status", "error_code", "provider_reference"]
            }
            for row in deliveries
        ],
    }


async def dispatch_report(session: AsyncSession, report_id: uuid.UUID) -> None:
    # Claim and commit BEFORE the external side effect. A crash leaves SENDING, never auto-retried.
    for channel in ["email", "whatsapp"]:
        report = await require(session, NotificationReport, report_id, lock=True)
        if report.mode != get_settings().notification_mode:
            raise HTTPException(409, "Report delivery mode changed; create a new report")
        rows = list(
            (
                await session.scalars(
                    select(NotificationDelivery)
                    .where(
                        NotificationDelivery.report_id == report_id,
                        NotificationDelivery.channel == channel,
                        NotificationDelivery.status == "PENDING",
                    )
                    .with_for_update()
                )
            ).all()
        )
        if not rows:
            await session.commit()
            continue
        preferences = await settings_view(session, report.candidate_id)
        if (
            not preferences[f"{channel}_enabled"]
            or get_settings().notification_mode == "live"
            and (not preferences["enabled"] or not preferences["consented_at"])
        ):
            for row in rows:
                row.status, row.error_code = "CANCELLED", "CONSENT_DISABLED"
            await session.commit()
            continue
        recipient = preferences["email" if channel == "email" else "whatsapp_number"] or "mock"
        selected_ids = {str(row.job_id) for row in rows}
        items = [item for item in report.content["items"] if item["job_id"] in selected_ids]
        # Recheck review decisions immediately before dispatch; no repeated reports after decision.
        for item in list(items):
            latest = await session.scalar(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.candidate_id == report.candidate_id,
                    ApprovalRequest.job_id == uuid.UUID(item["job_id"]),
                )
                .order_by(ApprovalRequest.created_at.desc())
                .limit(1)
            )
            if (
                latest
                and latest.status != "PENDING"
                and str(latest.resume_version_id) == item["resume_version_id"]
            ):
                items.remove(item)
                for row in rows:
                    if str(row.job_id) == item["job_id"]:
                        row.status = "CANCELLED"
        rows = [row for row in rows if row.status == "PENDING"]
        if not rows:
            await session.commit()
            continue
        ids = [row.id for row in rows]
        for row in rows:
            row.status = "SENDING"
        report_url = (
            f"{get_settings().dashboard_url}/?candidate={report.candidate_id}&report={report.id}"
        )
        text = "AI Job Hunter report\n\n" + "\n\n".join(
            f"{item['title']} — {item['company']}\nScore: {item['score']} | {item['decision']}\n"
            + "\n".join(item["source_links"])
            + "\n"
            + "\n".join(
                f"{fmt.upper()} resume: {get_settings().dashboard_url}/api/backend/"
                + path.removeprefix("/api/v1/")
                for fmt, path in item["resume_links"].items()
            )
            + f"\nReview: {item['review_url']}"
            for item in items
        )
        await session.commit()
        try:
            status, reference = await send_report(
                get_settings(),
                channel,
                recipient,
                f"AI Job Hunter: {len(items)} opportunities",
                text,
                report_url,
            )
            error = None
        except DeliveryError as exc:
            status, reference, error = "UNKNOWN" if exc.uncertain else "FAILED", None, exc.code
        except Exception:
            status, reference, error = "UNKNOWN", None, "DELIVERY_OUTCOME_UNKNOWN"
        completed = (
            await session.scalars(
                select(NotificationDelivery)
                .where(NotificationDelivery.id.in_(ids))
                .with_for_update()
            )
        ).all()
        for row in completed:
            row.status, row.provider_reference, row.error_code = status, reference, error
        await session.commit()
    report = await require(session, NotificationReport, report_id, lock=True)
    statuses = list(
        (
            await session.scalars(
                select(NotificationDelivery.status).where(
                    NotificationDelivery.report_id == report_id
                )
            )
        ).all()
    )
    report.status = (
        "PREVIEW"
        if report.status == "PREVIEW"
        else "EMPTY"
        if not statuses
        else "ATTENTION_REQUIRED"
        if any(s in {"FAILED", "UNKNOWN", "SENDING"} for s in statuses)
        else "COMPLETE"
    )
    await session.commit()
