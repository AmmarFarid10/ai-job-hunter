import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import DateTime, cast, select

from app.agents.discovery import run_discovery
from app.api.dependencies import Session, authenticate
from app.config import get_settings
from app.domain.discovery import DiscoveryRequest, EmailImport
from app.integrations.discovery.email import ImportedEmailProvider
from app.integrations.discovery.registry import ProviderRegistry, get_registry
from app.models import AgentExecution, DiscoveryItem
from app.repositories.common import require
from app.schemas import JobCreate
from app.services.discovery import execution_view, item_view, review_item

router = APIRouter(
    prefix="/api/v1/discovery", tags=["discovery"], dependencies=[Depends(authenticate)]
)
Registry = Annotated[ProviderRegistry, Depends(get_registry)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=1_000_000)]


def private_source_guard(registry: ProviderRegistry, session: Session) -> ProviderRegistry:
    # The server's Gmail token belongs to the operator, never to public signups.
    from app.integrations.discovery.email import GmailAlertProvider

    if session.info.get("role") == "ADMIN":
        return registry
    blocked = {
        name
        for name, provider in registry.providers.items()
        if isinstance(provider, GmailAlertProvider)
    }
    return ProviderRegistry(
        {name: provider for name, provider in registry.providers.items() if name not in blocked},
        [item for item in registry.descriptions if item["name"] not in blocked],
    )


@router.get("/providers")
async def providers(registry: Registry, session: Session) -> list[dict[str, Any]]:
    return private_source_guard(registry, session).descriptions


@router.post("/runs", status_code=201)
async def discover(data: DiscoveryRequest, session: Session, registry: Registry) -> dict[str, Any]:
    if get_settings().environment == "production":
        data.posted_within_days = 7
    return await run_discovery(
        session,
        data,
        private_source_guard(registry, session),
        get_settings().discovery_timeout_seconds,
    )


@router.get("/runs")
async def runs(session: Session, limit: Limit = 50, offset: Offset = 0) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(AgentExecution)
        .where(AgentExecution.agent_name == "job_discovery")
        .order_by(AgentExecution.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [execution_view(row) for row in rows]


@router.get("/runs/{run_id}")
async def run(run_id: uuid.UUID, session: Session) -> dict[str, Any]:
    execution = await require(session, AgentExecution, run_id)
    if execution.agent_name != "job_discovery":
        raise HTTPException(404, "Discovery run not found")
    return execution_view(execution)


@router.post("/import-email", status_code=201)
async def import_email(data: EmailImport, session: Session) -> dict[str, Any]:
    import hashlib

    # Hash the content into the request fingerprint without persisting the full email.
    request = DiscoveryRequest(
        sources=["email-import"],
        max_items=100,
        idempotency_key=data.idempotency_key,
        search_terms=[hashlib.sha256(data.raw_email.encode()).hexdigest()],
    )
    registry = ProviderRegistry({"email-import": ImportedEmailProvider(data.raw_email)})
    return await run_discovery(session, request, registry, get_settings().discovery_timeout_seconds)


@router.get("/items")
async def items(
    session: Session,
    status: Literal["REVIEW_REQUIRED", "CONFLICT", "IMPORTED", "DISMISSED"] | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
    provider: Annotated[str | None, Query(max_length=80)] = None,
    posted_within_days: Annotated[int | None, Query(ge=7, le=7)] = None,
) -> list[dict[str, Any]]:
    query = select(DiscoveryItem)
    if provider:
        query = query.where(DiscoveryItem.provider == provider)
    if status:
        query = query.where(DiscoveryItem.status == status)
    if posted_within_days is not None:
        now = datetime.now(UTC)
        posted = cast(DiscoveryItem.payload["posted_at"].as_string(), DateTime(timezone=True))
        query = query.where(posted >= now - timedelta(days=7), posted <= now)
    rows = await session.scalars(
        query.order_by(DiscoveryItem.created_at.desc()).limit(limit).offset(offset)
    )
    return [item_view(row) for row in rows]


@router.get("/items/{item_id}")
async def get_item(item_id: uuid.UUID, session: Session) -> dict[str, Any]:
    return item_view(await require(session, DiscoveryItem, item_id))


@router.post("/items/{item_id}/import")
async def import_item(item_id: uuid.UUID, data: JobCreate, session: Session) -> dict[str, Any]:
    return await review_item(session, item_id, data)


@router.post("/items/{item_id}/dismiss")
async def dismiss_item(item_id: uuid.UUID, session: Session) -> dict[str, Any]:
    item = await require(session, DiscoveryItem, item_id, lock=True)
    if item.status in {"IMPORTED", "DISMISSED"}:
        raise HTTPException(409, "Observation has already been reviewed/imported")
    item.status = "DISMISSED"
    item.reviewed_at = datetime.now(UTC)
    item.review_note = "Dismissed by owner"
    await session.flush()
    return item_view(item)
