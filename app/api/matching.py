import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.agents.matching import run_matching
from app.api.dependencies import Session, authenticate
from app.config import get_settings
from app.domain.matching import MatchingRequest, RequirementReview
from app.integrations.discovery.base import ProviderError
from app.integrations.discovery.http import SafeHTTP
from app.integrations.matching.openai import OpenAIExtractor
from app.integrations.matching.rules import RulesExtractor
from app.models import AgentExecution, Candidate, CandidatePreference, Job, JobAnalysis, JobMatch
from app.repositories.common import require
from app.repositories.matching import facts_hash, load_candidate
from app.schemas import PreferenceReview
from app.services.discovery import execution_view
from app.services.matching import analysis_view, get_analysis, match_view, save_analysis

router = APIRouter(
    prefix="/api/v1/matching", tags=["matching"], dependencies=[Depends(authenticate)]
)
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=1_000_000)]


@router.post("/runs", status_code=201)
async def create_run(data: MatchingRequest, session: Session) -> dict[str, Any]:
    settings = get_settings()
    if data.extractor == "openai":
        if not settings.openai_api_key or not settings.openai_extraction_model:
            raise HTTPException(422, "OpenAI extraction is not configured; use rules")
        return await run_matching(
            session,
            data,
            OpenAIExtractor(
                SafeHTTP({"api.openai.com"}, timeout=25),
                settings.openai_api_key,
                settings.openai_extraction_model,
            ),
            settings.matching_timeout_seconds,
        )
    return await run_matching(session, data, RulesExtractor(), settings.matching_timeout_seconds)


@router.get("/runs")
async def runs(session: Session, limit: Limit = 50, offset: Offset = 0) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(AgentExecution)
        .where(AgentExecution.agent_name == "job_matching")
        .order_by(AgentExecution.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [execution_view(row) for row in rows]


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, session: Session) -> dict[str, Any]:
    row = await require(session, AgentExecution, run_id)
    if row.agent_name != "job_matching":
        raise HTTPException(404, "Matching execution not found")
    return execution_view(row)


@router.get("/candidates/{candidate_id}/matches")
async def matches(
    candidate_id: uuid.UUID,
    session: Session,
    qualified_only: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[dict[str, Any]]:
    profile_hash = facts_hash(await load_candidate(session, candidate_id))
    query = select(JobMatch).where(JobMatch.candidate_id == candidate_id)
    if qualified_only:
        query = query.where(JobMatch.decision == "QUALIFIED")
    rows = await session.scalars(
        query.order_by(
            JobMatch.score.desc(),
            JobMatch.explanation["remote_priority"].as_integer().desc().nullslast(),
            JobMatch.job_id,
        )
        .limit(limit)
        .offset(offset)
    )
    views = [await match_view(session, row, profile_hash) for row in rows]
    return [view for view in views if view["qualified"]] if qualified_only else views


@router.get("/candidates/{candidate_id}/matches/{job_id}")
async def match_detail(
    candidate_id: uuid.UUID, job_id: uuid.UUID, session: Session
) -> dict[str, Any]:
    row = await session.scalar(
        select(JobMatch).where(JobMatch.candidate_id == candidate_id, JobMatch.job_id == job_id)
    )
    if row is None:
        raise HTTPException(404, "Match not found; run matching first")
    return await match_view(session, row)


@router.get("/jobs/{job_id}/requirements")
async def requirements(job_id: uuid.UUID, session: Session) -> dict[str, Any]:
    job = await require(session, Job, job_id, lock=True)
    analysis = await session.scalar(select(JobAnalysis).where(JobAnalysis.job_id == job.id))
    if analysis is None:
        analysis = await get_analysis(session, job, RulesExtractor(), "rules")
    return analysis_view(analysis, job)


@router.put("/jobs/{job_id}/requirements")
async def review_requirements(
    job_id: uuid.UUID, data: RequirementReview, session: Session
) -> dict[str, Any]:
    job = await require(session, Job, job_id, lock=True)
    try:
        analysis = await save_analysis(session, job, data.requirements, "owner", reviewed=True)
    except ProviderError as exc:
        raise HTTPException(422, exc.code) from exc
    return analysis_view(analysis, job)


@router.put("/candidates/{candidate_id}/preferences")
async def update_preferences(
    candidate_id: uuid.UUID, data: PreferenceReview, session: Session
) -> dict[str, Any]:
    await require(session, Candidate, candidate_id, lock=True)
    row = await session.scalar(
        select(CandidatePreference).where(CandidatePreference.candidate_id == candidate_id)
    )
    if row is None:
        row = CandidatePreference(candidate_id=candidate_id)
        session.add(row)
    for field, value in data.preferences.model_dump().items():
        setattr(row, field, value)
    await session.flush()
    return data.preferences.model_dump(mode="json")
