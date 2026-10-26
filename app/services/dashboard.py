import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentExecution,
    Application,
    ApprovalRequest,
    Candidate,
    DiscoveryItem,
    Job,
    JobMatch,
    JobSource,
    NotificationReport,
    ResumeVersion,
)
from app.repositories.common import require
from app.services.applications import application_view
from app.services.approvals import approval_view
from app.services.matching import match_view
from app.services.notifications import report_view, settings_view
from app.services.profiles import profile_view
from app.services.tailoring import version_view


async def overview(session: AsyncSession, candidate_id: uuid.UUID) -> dict[str, Any]:
    candidate = await require(session, Candidate, candidate_id)
    matches = (
        await session.scalars(
            select(JobMatch)
            .where(JobMatch.candidate_id == candidate_id)
            .order_by(JobMatch.score.desc(), JobMatch.id)
            .limit(100)
        )
    ).all()
    jobs: list[dict[str, Any]] = []
    for match in matches:
        job = await require(session, Job, match.job_id)
        jobs.append(
            {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "application_url": job.application_url,
                "description": job.description,
                "match": await match_view(session, match),
            }
        )
    matched_ids = {item["id"] for item in jobs}
    unmatched = (
        await session.scalars(
            select(Job)
            .where(Job.id.not_in(matched_ids))
            .order_by(Job.created_at.desc())
            .limit(max(0, 100 - len(jobs)))
        )
    ).all()
    for job in unmatched:
        jobs.append(
            {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "application_url": job.application_url,
                "description": job.description,
                "match": {
                    "score": 0,
                    "decision": "NOT_EVALUATED",
                    "stale": True,
                    "qualified": False,
                    "explanation": {"message": "Run matching first"},
                },
            }
        )
    for item in jobs:
        item["source_links"] = list(
            (
                await session.scalars(
                    select(JobSource.url)
                    .where(JobSource.job_id == item["id"])
                    .order_by(JobSource.id)
                )
            ).all()
        )
    leads = (
        await session.scalars(
            select(DiscoveryItem)
            .where(DiscoveryItem.status == "REVIEW_REQUIRED")
            .order_by(DiscoveryItem.created_at.desc())
            .limit(100)
        )
    ).all()
    versions = (
        await session.scalars(
            select(ResumeVersion)
            .where(ResumeVersion.candidate_id == candidate_id)
            .order_by(ResumeVersion.created_at.desc())
            .limit(100)
        )
    ).all()
    approvals = (
        await session.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.candidate_id == candidate_id)
            .order_by(ApprovalRequest.created_at.desc())
            .limit(100)
        )
    ).all()
    applications = (
        await session.scalars(
            select(Application)
            .where(Application.candidate_id == candidate_id)
            .order_by(Application.created_at.desc())
            .limit(100)
        )
    ).all()
    executions = (
        await session.scalars(
            select(AgentExecution).order_by(AgentExecution.created_at.desc()).limit(50)
        )
    ).all()
    reports = (
        await session.scalars(
            select(NotificationReport)
            .where(NotificationReport.candidate_id == candidate_id)
            .order_by(NotificationReport.created_at.desc())
            .limit(20)
        )
    ).all()
    return {
        "candidate": await profile_view(session, candidate),
        "jobs": jobs,
        "discovery_leads": [
            {"id": row.id, "provider": row.provider, "status": row.status, "payload": row.payload}
            for row in leads
        ],
        "resumes": [await version_view(session, row) for row in versions],
        "approvals": [await approval_view(session, row) for row in approvals],
        "applications": [await application_view(session, row) for row in applications],
        "executions": [
            {
                key: getattr(row, key)
                for key in ["id", "agent_name", "status", "created_at", "completed_at", "summary"]
            }
            for row in executions
        ],
        "reports": [await report_view(session, row) for row in reports],
        "notification_settings": await settings_view(session, candidate_id),
        "counts": {
            "discovered_jobs": await session.scalar(select(func.count()).select_from(Job)),
            "discovery_review": await session.scalar(
                select(func.count())
                .select_from(DiscoveryItem)
                .where(DiscoveryItem.status == "REVIEW_REQUIRED")
            ),
            "qualified": sum(job["match"]["qualified"] for job in jobs),
            "review_required": sum(job["match"]["decision"] == "REVIEW_REQUIRED" for job in jobs),
        },
        "limits": {
            "matches": 100,
            "resumes": 100,
            "approvals": 100,
            "applications": 100,
            "executions": 50,
            "reports": 20,
        },
    }
