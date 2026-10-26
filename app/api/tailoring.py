import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select

from app.api.dependencies import Session, authenticate
from app.config import get_settings
from app.domain.tailoring import TailoringRequest
from app.models import ResumeVersion
from app.repositories.common import require
from app.services.tailoring import artifact_bytes, generate_resume, version_view

router = APIRouter(
    prefix="/api/v1/resumes", tags=["resume tailoring"], dependencies=[Depends(authenticate)]
)


@router.post("/generations", status_code=201)
async def generate(data: TailoringRequest, session: Session) -> dict[str, Any]:
    return await generate_resume(session, data, get_settings())


@router.get("/versions")
async def versions(
    candidate_id: uuid.UUID,
    job_id: uuid.UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(ResumeVersion)
        .where(ResumeVersion.candidate_id == candidate_id, ResumeVersion.job_id == job_id)
        .order_by(ResumeVersion.version.desc())
        .limit(limit)
        .offset(offset)
    )
    return [await version_view(session, row) for row in rows]


@router.get("/versions/{version_id}")
async def version(version_id: uuid.UUID, session: Session) -> dict[str, Any]:
    return await version_view(session, await require(session, ResumeVersion, version_id))


@router.get("/versions/{version_id}/download/{format}")
async def download(
    version_id: uuid.UUID, format: Literal["docx", "pdf"], session: Session
) -> Response:
    row = await require(session, ResumeVersion, version_id)
    content = await artifact_bytes(row, format, get_settings())
    media = (
        "application/pdf"
        if format == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return Response(
        content=content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="resume-v{row.version}.{format}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/versions/{version_id}/preview/{page}")
async def preview(version_id: uuid.UUID, page: int, session: Session) -> Response:
    from fastapi import HTTPException
    from starlette.concurrency import run_in_threadpool

    from app.integrations.documents.preview import preview_page

    row = await require(session, ResumeVersion, version_id)
    content = await artifact_bytes(row, "pdf", get_settings())
    try:
        png = await run_in_threadpool(preview_page, content, page)
    except IndexError as exc:
        raise HTTPException(404, "Resume preview page not found") from exc
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})
