import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, SecretStr
from sqlalchemy import select, text

from app.api.dependencies import Session, administrator, authenticate
from app.config import get_settings
from app.models import AdminAudit, WorkspaceAccount
from app.services.auth import account_view

router = APIRouter(
    prefix="/api/v1/admin", dependencies=[Depends(authenticate)], tags=["administration"]
)


class Bootstrap(BaseModel):
    setup_key: SecretStr


@router.post("/bootstrap")
async def bootstrap(data: Bootstrap, session: Session) -> dict[str, Any]:
    if not get_settings().allow_admin_bootstrap:
        raise HTTPException(404, "Not found")
    actor = session.info.get("actor_id")
    if actor is None:
        raise HTTPException(401, "Sign in to the account to promote")
    if not secrets.compare_digest(
        data.setup_key.get_secret_value().encode(),
        get_settings().api_key.get_secret_value().encode(),
    ):
        raise HTTPException(403, "Valid administrator setup key required")
    await session.execute(text("SELECT pg_advisory_xact_lock(710002001)"))
    existing = await session.scalar(
        select(WorkspaceAccount.id).where(
            WorkspaceAccount.role == "ADMIN", WorkspaceAccount.password_hash != "!bootstrap"
        )
    )
    if existing:
        raise HTTPException(409, "An administrator is already configured")
    account = await session.get(WorkspaceAccount, actor)
    assert account is not None
    account.role = "ADMIN"
    session.add(
        AdminAudit(
            actor_account_id=actor,
            target_account_id=actor,
            method="POST",
            resource="/api/v1/admin/bootstrap",
        )
    )
    await session.flush()
    return {"user": account_view(account)}


@router.get("/users", dependencies=[Depends(administrator)])
async def users(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> list[dict[str, Any]]:
    accounts = (
        await session.scalars(
            select(WorkspaceAccount)
            .order_by(WorkspaceAccount.created_at, WorkspaceAccount.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [account_view(account) for account in accounts]


@router.get("/audit", dependencies=[Depends(administrator)])
async def audit(
    session: Session, limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(AdminAudit).order_by(AdminAudit.created_at.desc()).limit(limit)
    )
    return [
        {
            "id": row.id,
            "actor_account_id": row.actor_account_id,
            "target_account_id": row.target_account_id,
            "method": row.method,
            "resource": row.resource,
            "created_at": row.created_at,
        }
        for row in rows
    ]
