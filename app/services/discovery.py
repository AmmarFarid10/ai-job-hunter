import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.discovery import Listing
from app.models import AgentExecution, DiscoveryItem
from app.repositories.common import require
from app.repositories.discovery import try_run_lock
from app.schemas import JobCreate
from app.services.jobs import create_job, job_view


def request_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def reserve_run(
    session: AsyncSession, key: str, payload: dict[str, Any]
) -> tuple[AgentExecution, bool]:
    await try_run_lock(session, key)
    hashed = request_hash(payload)
    existing = await session.scalar(
        select(AgentExecution).where(AgentExecution.idempotency_key == key)
    )
    if existing:
        if existing.request_hash != hashed:
            raise HTTPException(409, "Discovery key was used with different parameters")
        return existing, False
    # Bound concurrent network runs and avoid multi-job lock-order cycles.
    await try_run_lock(session, "global-discovery-run")
    execution = AgentExecution(
        agent_name="job_discovery",
        status="RUNNING",
        idempotency_key=key,
        request_hash=hashed,
        summary={},
    )
    session.add(execution)
    await session.flush()
    return execution, True


async def store_listing(
    session: AsyncSession, execution_id: uuid.UUID, provider: str, listing: Listing
) -> dict[str, Any]:
    # Shared provider/external identity lock avoids observation races across distinct run keys.
    await try_run_lock(session, "item:" + provider + ":" + listing.external_id)
    existing = await session.scalar(
        select(DiscoveryItem).where(
            DiscoveryItem.provider == provider,
            DiscoveryItem.external_id == listing.external_id,
        )
    )
    if existing:
        if listing.posted_at is not None and listing.posting_date_evidence:
            existing.payload = {
                **existing.payload,
                "posted_at": listing.posted_at.isoformat(),
                "posting_date_evidence": listing.posting_date_evidence,
            }
        return {
            "outcome": "seen",
            "item_id": str(existing.id),
            "job_id": str(existing.job_id) if existing.job_id else None,
            "status": existing.status,
        }
    item = DiscoveryItem(
        execution_id=execution_id,
        provider=provider,
        external_id=listing.external_id,
        payload=listing.model_dump(mode="json"),
        status="REVIEW_REQUIRED",
    )
    session.add(item)
    await session.flush()
    if listing.requires_review or not listing.company:
        return {
            "outcome": "review_required",
            "item_id": str(item.id),
            "job_id": None,
            "status": item.status,
        }
    try:
        data = listing.as_job(provider)
        async with session.begin_nested():
            job, created, possible = await create_job(session, data)
    except (HTTPException, IntegrityError, ValueError):
        item.status = "CONFLICT"
        item.review_note = "Vacancy identity or required fields need manual review"
        return {
            "outcome": "conflict",
            "item_id": str(item.id),
            "job_id": None,
            "status": item.status,
        }
    item.job_id = job.id
    item.status = "IMPORTED"
    return {
        "outcome": "created" if created else "deduplicated",
        "item_id": str(item.id),
        "job_id": str(job.id),
        "status": item.status,
        "possible_duplicate_ids": possible,
    }


async def review_item(session: AsyncSession, item_id: uuid.UUID, data: JobCreate) -> dict[str, Any]:
    item = await require(session, DiscoveryItem, item_id, lock=True)
    if item.status in {"IMPORTED", "DISMISSED"}:
        raise HTTPException(409, "Observation has already been reviewed/imported")
    # User corrections are explicit; original untrusted payload remains available for comparison.
    job, created, possible = await create_job(session, data)
    item.job_id = job.id
    item.status = "IMPORTED"
    item.reviewed_at = datetime.now(UTC)
    item.review_note = "Owner supplied corrected job fields"
    await session.flush()
    return {
        "job": await job_view(session, job),
        "created": created,
        "possible_duplicate_ids": possible,
    }


def execution_view(execution: AgentExecution) -> dict[str, Any]:
    return {
        "id": execution.id,
        "agent_name": execution.agent_name,
        "status": execution.status,
        "created_at": execution.created_at,
        "completed_at": execution.completed_at,
        "summary": execution.summary,
    }


def item_view(item: DiscoveryItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "execution_id": item.execution_id,
        "provider": item.provider,
        "external_id": item.external_id,
        "status": item.status,
        "payload": item.payload,
        "job_id": item.job_id,
        "review_note": item.review_note,
        "reviewed_at": item.reviewed_at,
        "created_at": item.created_at,
    }
