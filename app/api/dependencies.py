import secrets
import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.models import AdminAudit, WorkspaceAccount

header = APIKeyHeader(name="X-API-Key", auto_error=False)
Session = Annotated[AsyncSession, Depends(get_session, scope="function")]


async def authenticate(
    request: Request,
    key: Annotated[str | None, Security(header)],
    session: Session,
    owner_token: Annotated[str | None, Header(alias="X-Owner-Session")] = None,
    workspace_user: Annotated[uuid.UUID | None, Header(alias="X-Workspace-User")] = None,
) -> None:
    from app.services.auth import current_session

    session.info.clear()
    expected = get_settings().api_key.get_secret_value()
    if (
        get_settings().allow_api_key_auth
        and key is not None
        and secrets.compare_digest(key.encode(), expected.encode())
    ):
        session.info.update(system=True, role="ADMIN")
        if workspace_user:
            if await session.get(WorkspaceAccount, workspace_user) is None:
                raise HTTPException(404, "Workspace not found")
            session.info.update(system=False, owner_id=workspace_user)
        return
    login = await current_session(session, owner_token)
    account = await session.get(WorkspaceAccount, login.account_id)
    if account is None:
        raise HTTPException(401, "Sign in required")
    if get_settings().require_email_verification and account.email_verified_at is None:
        raise HTTPException(403, "Verify your email before accessing your workspace")
    owner = workspace_user or account.id
    if owner != account.id:
        if account.role != "ADMIN":
            raise HTTPException(403, "Administrator access required")
        if await session.get(WorkspaceAccount, owner) is None:
            raise HTTPException(404, "Workspace not found")
        session.add(
            AdminAudit(
                actor_account_id=account.id,
                target_account_id=owner,
                method=request.method,
                resource=request.url.path,
            )
        )
    session.info.update(owner_id=owner, actor_id=account.id, role=account.role)


async def administrator(session: Session) -> None:
    if session.info.get("role") != "ADMIN":
        raise HTTPException(403, "Administrator access required")
