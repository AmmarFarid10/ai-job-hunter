import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.states import State, validate_transition
from app.models import Application, ApplicationEvent, Candidate, Job
from app.repositories.common import require
from app.schemas import ApplicationCreate, Transition


async def create_application(session: AsyncSession, data: ApplicationCreate) -> Application:
    await require(session, Candidate, data.candidate_id)
    await require(session, Job, data.job_id)
    existing = await session.scalar(
        select(Application).where(Application.idempotency_key == data.idempotency_key)
    )
    if existing:
        if (existing.candidate_id, existing.job_id) != (data.candidate_id, data.job_id):
            raise HTTPException(409, "Idempotency key was used with different application details")
        return existing
    application = Application(**data.model_dump(), state=State.DISCOVERED)
    session.add(application)
    await session.flush()
    session.add(
        ApplicationEvent(
            application_id=application.id,
            from_state=None,
            to_state=State.DISCOVERED,
            reason="Application record created",
        )
    )
    await session.flush()
    return application


async def transition(
    session: AsyncSession, application_id: uuid.UUID, data: Transition
) -> Application:
    application = await require(session, Application, application_id, lock=True)
    if application.approval_request_id is not None:
        raise HTTPException(
            409, "Use the exact-version approval workflow for reviewed applications"
        )
    current = State(application.state)
    try:
        validate_transition(current, data.state)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    application.state = data.state.value
    session.add(
        ApplicationEvent(
            application_id=application.id,
            from_state=current.value,
            to_state=data.state.value,
            reason=data.reason,
        )
    )
    await session.flush()
    return application


async def application_view(session: AsyncSession, application: Application) -> dict[str, Any]:
    result = {
        column.name: getattr(application, column.name) for column in Application.__table__.columns
    }
    events = await session.scalars(
        select(ApplicationEvent)
        .where(
            ApplicationEvent.application_id == application.id,
        )
        .order_by(ApplicationEvent.created_at, ApplicationEvent.id)
    )
    result["events"] = [
        {
            "from_state": row.from_state,
            "to_state": row.to_state,
            "reason": row.reason,
            "actor": row.actor,
            "created_at": row.created_at,
        }
        for row in events
    ]
    return result
