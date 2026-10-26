import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import Session, authenticate
from app.domain.approvals import ApprovalCreate, ApprovalDecision, NotificationPreferences
from app.models import ApprovalRequest, NotificationReport
from app.repositories.common import require
from app.schemas import Preferences
from app.services.approvals import approval_view, create_approval, decide
from app.services.notifications import (
    build_report,
    dispatch_report,
    report_view,
    save_settings,
    settings_view,
)

router = APIRouter(
    prefix="/api/v1", dependencies=[Depends(authenticate)], tags=["review and reports"]
)


@router.post("/approvals", status_code=201)
async def add_approval(data: ApprovalCreate, session: Session) -> dict[str, Any]:
    return await create_approval(session, data)


@router.get("/approvals")
async def list_approvals(
    candidate_id: uuid.UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.candidate_id == candidate_id)
            .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [await approval_view(session, row) for row in rows]


@router.get("/approvals/{approval_id}")
async def get_approval(approval_id: uuid.UUID, session: Session) -> dict[str, Any]:
    return await approval_view(session, await require(session, ApprovalRequest, approval_id))


@router.post("/approvals/{approval_id}/decision")
async def decision(
    approval_id: uuid.UUID, data: ApprovalDecision, session: Session
) -> dict[str, Any]:
    return await decide(session, approval_id, data)


@router.get("/notifications/settings/{candidate_id}")
async def get_settings(candidate_id: uuid.UUID, session: Session) -> dict[str, Any]:
    return await settings_view(session, candidate_id)


@router.put("/notifications/settings/{candidate_id}")
async def put_settings(
    candidate_id: uuid.UUID, data: NotificationPreferences, session: Session
) -> dict[str, Any]:
    return await save_settings(session, candidate_id, data)


class ReportCreate(BaseModel):
    candidate_id: uuid.UUID
    idempotency_key: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        min_length=1,
        max_length=70,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    deliver: bool = False


@router.post("/notifications/reports", status_code=201)
async def add_report(data: ReportCreate, session: Session) -> dict[str, Any]:
    from app.services.quotas import reserve_usage

    await reserve_usage(session, "report")
    report = await build_report(
        session, data.candidate_id, "manual:" + data.idempotency_key, data.deliver
    )
    report_id = report.id
    # Commit outbox before sending; a separate unit of work handles dispatch and its commits.
    await session.commit()
    async with AsyncSession(
        bind=session.bind, expire_on_commit=False, info=dict(session.info)
    ) as worker:
        if data.deliver:
            await dispatch_report(worker, report_id)
        return await report_view(worker, await require(worker, NotificationReport, report_id))


@router.get("/notifications/reports")
async def reports(
    candidate_id: uuid.UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(NotificationReport)
            .where(NotificationReport.candidate_id == candidate_id)
            .order_by(NotificationReport.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [await report_view(session, row) for row in rows]


@router.get("/notifications/reports/{report_id}")
async def get_report(report_id: uuid.UUID, session: Session) -> dict[str, Any]:
    return await report_view(session, await require(session, NotificationReport, report_id))


@router.put("/candidates/{candidate_id}/preferences")
async def preferences(
    candidate_id: uuid.UUID, data: Preferences, session: Session
) -> dict[str, Any]:
    from app.models import Candidate, CandidatePreference

    await require(session, Candidate, candidate_id, lock=True)
    row = await session.scalar(
        select(CandidatePreference).where(CandidatePreference.candidate_id == candidate_id)
    )
    if row is None:
        row = CandidatePreference(candidate_id=candidate_id)
        session.add(row)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    await session.flush()
    return data.model_dump(mode="json")


class ContactUpdate(BaseModel):
    email: str = Field(max_length=320, pattern=r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
    confirmed: Literal[True]


@router.put("/candidates/{candidate_id}/contact")
async def contact(candidate_id: uuid.UUID, data: ContactUpdate, session: Session) -> dict[str, Any]:
    from app.models import Candidate
    from app.services.profiles import profile_view

    row = await require(session, Candidate, candidate_id, lock=True)
    if not row.verified:
        from fastapi import HTTPException

        raise HTTPException(409, "Confirm the full profile before updating its contact")
    row.email = data.email
    await session.flush()
    return await profile_view(session, row)
