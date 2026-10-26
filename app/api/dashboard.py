import uuid
from typing import Any

from fastapi import APIRouter, Depends

from app.api.dependencies import Session, authenticate
from app.services.dashboard import overview

router = APIRouter(
    prefix="/api/v1/dashboard", tags=["dashboard"], dependencies=[Depends(authenticate)]
)


@router.get("/{candidate_id}")
async def dashboard(candidate_id: uuid.UUID, session: Session) -> dict[str, Any]:
    return await overview(session, candidate_id)
