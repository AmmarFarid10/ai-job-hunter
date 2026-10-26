import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select

from app.api.dependencies import Session, authenticate
from app.config import get_settings
from app.models import Application, Candidate, CandidatePreference, Job, ResumeDraft
from app.repositories.common import require
from app.schemas import (
    ApplicationCreate,
    CandidateCreate,
    JobCreate,
    Preferences,
    ProfileUpdate,
    Transition,
)
from app.services.applications import application_view, create_application, transition
from app.services.jobs import create_job, job_view
from app.services.profiles import confirm_draft, fields, profile_view, update_profile
from app.services.resumes import ingest_resume

router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=1_000_000)]


@router.post("/candidates", status_code=201)
async def add_candidate(data: CandidateCreate, session: Session) -> dict[str, Any]:
    if not session.info.get("system"):
        # Serialize candidate creation per owner so concurrent requests cannot exceed the cap.
        from app.models import WorkspaceAccount

        await session.scalar(
            select(WorkspaceAccount)
            .where(WorkspaceAccount.id == session.info["owner_id"])
            .with_for_update()
        )
        count = await session.scalar(select(func.count()).select_from(Candidate))
        if count is not None and count >= get_settings().max_candidates_per_user:
            from fastapi import HTTPException

            raise HTTPException(429, "Candidate profile limit reached")
    candidate = Candidate(**data.model_dump())
    session.add(candidate)
    await session.flush()
    session.add(
        CandidatePreference(
            candidate_id=candidate.id,
            **Preferences(match_threshold=get_settings().match_threshold).model_dump(),
        )
    )
    await session.flush()
    return await profile_view(session, candidate)


@router.get("/candidates")
async def list_candidates(
    session: Session, limit: Limit = 50, offset: Offset = 0
) -> list[dict[str, Any]]:
    candidates = await session.scalars(
        select(Candidate).order_by(Candidate.created_at).limit(limit).offset(offset)
    )
    return [fields(row, ["id", "name", "verified"]) for row in candidates]


@router.get("/candidates/{candidate_id}")
async def get_candidate(candidate_id: uuid.UUID, session: Session) -> dict[str, Any]:
    return await profile_view(session, await require(session, Candidate, candidate_id))


@router.put("/candidates/{candidate_id}/profile")
async def put_profile(
    candidate_id: uuid.UUID, data: ProfileUpdate, session: Session
) -> dict[str, Any]:
    return await profile_view(session, await update_profile(session, candidate_id, data))


def draft_view(draft: ResumeDraft) -> dict[str, Any]:
    return fields(
        draft,
        [
            "id",
            "candidate_id",
            "sha256",
            "extracted_text",
            "suggestions",
            "warnings",
            "reviewed_at",
            "created_at",
            "confirmed_profile",
        ],
    )


@router.post("/candidates/{candidate_id}/resumes", status_code=201)
async def upload_resume(
    candidate_id: uuid.UUID, session: Session, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    return draft_view(await ingest_resume(session, candidate_id, file, get_settings()))


@router.get("/candidates/{candidate_id}/resumes/{draft_id}")
async def get_draft(
    candidate_id: uuid.UUID, draft_id: uuid.UUID, session: Session
) -> dict[str, Any]:
    from fastapi import HTTPException

    draft = await require(session, ResumeDraft, draft_id)
    if draft.candidate_id != candidate_id:
        raise HTTPException(404, "ResumeDraft not found")
    return draft_view(draft)


@router.get("/candidates/{candidate_id}/resumes")
async def list_master_resumes(
    candidate_id: uuid.UUID, session: Session, limit: Limit = 20, offset: Offset = 0
) -> list[dict[str, Any]]:
    await require(session, Candidate, candidate_id)
    drafts = (
        await session.scalars(
            select(ResumeDraft)
            .where(ResumeDraft.candidate_id == candidate_id)
            .order_by(ResumeDraft.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [draft_view(row) for row in drafts]


@router.get("/candidates/{candidate_id}/resumes/{draft_id}/download")
async def download_master(
    candidate_id: uuid.UUID, draft_id: uuid.UUID, session: Session
) -> Response:
    from fastapi import HTTPException
    from starlette.concurrency import run_in_threadpool

    from app.integrations.documents.storage import ArtifactError, read_artifact

    draft = await require(session, ResumeDraft, draft_id)
    if draft.candidate_id != candidate_id:
        raise HTTPException(404, "ResumeDraft not found")
    try:
        content = await run_in_threadpool(
            read_artifact, get_settings().storage_dir, draft.storage_key, draft.sha256
        )
    except ArtifactError as exc:
        raise HTTPException(409, "Master resume file missing or modified") from exc
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="master-resume.pdf"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/candidates/{candidate_id}/resumes/{draft_id}/confirm")
async def confirm_resume(
    candidate_id: uuid.UUID, draft_id: uuid.UUID, data: ProfileUpdate, session: Session
) -> dict[str, Any]:
    return await profile_view(session, await confirm_draft(session, candidate_id, draft_id, data))


@router.post("/jobs", status_code=201)
async def add_job(data: JobCreate, session: Session) -> dict[str, Any]:
    job, created, possible = await create_job(session, data)
    return {
        "job": await job_view(session, job),
        "created": created,
        "possible_duplicate_ids": possible,
    }


@router.get("/jobs")
async def list_jobs(
    session: Session, limit: Limit = 50, offset: Offset = 0
) -> list[dict[str, Any]]:
    jobs = await session.scalars(select(Job).order_by(Job.created_at).limit(limit).offset(offset))
    return [await job_view(session, job) for job in jobs]


@router.get("/jobs/{job_id}")
async def get_job(job_id: uuid.UUID, session: Session) -> dict[str, Any]:
    return await job_view(session, await require(session, Job, job_id))


@router.post("/applications", status_code=201)
async def add_application(data: ApplicationCreate, session: Session) -> dict[str, Any]:
    return await application_view(session, await create_application(session, data))


@router.get("/applications")
async def list_applications(
    session: Session, limit: Limit = 50, offset: Offset = 0
) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(Application).order_by(Application.created_at).limit(limit).offset(offset)
    )
    return [await application_view(session, row) for row in rows]


@router.get("/applications/{application_id}")
async def get_application(application_id: uuid.UUID, session: Session) -> dict[str, Any]:
    return await application_view(session, await require(session, Application, application_id))


@router.post("/applications/{application_id}/transitions")
async def change_state(
    application_id: uuid.UUID, data: Transition, session: Session
) -> dict[str, Any]:
    return await application_view(session, await transition(session, application_id, data))
