import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict
from urllib.parse import urlsplit

from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.matching import POLICY_VERSION, MatchingRequest, MatchResult, Requirements
from app.domain.scoring import score_match
from app.integrations.discovery.base import ProviderError
from app.integrations.matching.rules import RequirementExtractor
from app.models import AgentExecution, JobMatch, JobSource
from app.repositories.discovery import try_run_lock
from app.repositories.matching import facts_hash, job_facts, load_candidate, select_jobs, today
from app.services.discovery import execution_view, request_hash
from app.services.matching import get_analysis


class MatchingState(TypedDict):
    analyses: dict[str, Requirements]
    results: list[tuple[uuid.UUID, MatchResult]]
    errors: list[dict[str, str]]
    skipped: list[str]


async def run_matching(
    session: AsyncSession,
    request: MatchingRequest,
    extractor: RequirementExtractor,
    budget_seconds: int,
) -> dict[str, Any]:
    await try_run_lock(session, "matching:run:" + request.idempotency_key)
    await try_run_lock(session, "matching:global")
    candidate = await load_candidate(session, request.candidate_id, lock=True)
    if not candidate.verified:
        raise HTTPException(409, "Confirm the candidate profile before matching")
    jobs = await select_jobs(session, request.job_ids)
    as_of = today()
    profile_hash = facts_hash(candidate)
    threshold = (
        request.threshold
        if request.threshold is not None
        else int(str(candidate.preferences.get("match_threshold", 80)))
    )
    payload: dict[str, Any] = {
        "request": request.model_dump(mode="json", exclude={"idempotency_key"}),
        "profile_hash": profile_hash,
        "as_of": as_of.isoformat(),
        "policy": POLICY_VERSION,
        "jobs": {str(job.id): facts_hash(job_facts(job)) for job in jobs},
    }
    hashed = request_hash(payload)
    execution_key = "matching:" + request.idempotency_key
    existing = await session.scalar(
        select(AgentExecution).where(AgentExecution.idempotency_key == execution_key)
    )
    if existing:
        if existing.agent_name != "job_matching" or existing.request_hash != hashed:
            raise HTTPException(409, "Matching inputs changed; use a new idempotency key")
        return {**execution_view(existing), "replayed": True}
    from app.services.quotas import reserve_usage

    await reserve_usage(session, "matching")
    execution = AgentExecution(
        agent_name="job_matching",
        idempotency_key=execution_key,
        request_hash=hashed,
        status="RUNNING",
        summary={},
    )
    session.add(execution)
    await session.flush()

    async def extract(state: MatchingState) -> dict[str, Any]:
        analyses = {}
        errors = []
        skipped = []
        try:
            async with asyncio.timeout(budget_seconds):
                for job in jobs:
                    host = urlsplit(job.application_url or "").hostname or ""
                    source_urls = list(
                        (
                            await session.scalars(
                                select(JobSource.url).where(JobSource.job_id == job.id)
                            )
                        ).all()
                    )
                    only_fixture_sources = bool(source_urls) and all(
                        (urlsplit(url).hostname or "").endswith(".invalid") for url in source_urls
                    )
                    if host.endswith(".invalid") or only_fixture_sources:
                        skipped.append(str(job.id))
                        continue
                    try:
                        analysis = await get_analysis(session, job, extractor, request.extractor)
                        analyses[str(job.id)] = Requirements.model_validate(analysis.requirements)
                    except ProviderError as exc:
                        errors.append({"job_id": str(job.id), "code": exc.code})
        except TimeoutError:
            # A cancelled database operation invalidates the transaction; let it roll back.
            # Normal HTTP timeouts are ProviderError and are isolated above.
            raise HTTPException(
                503, "Matching time budget exhausted; no batch was committed"
            ) from None
        return {"analyses": analyses, "errors": errors, "skipped": skipped}

    async def score(state: MatchingState) -> dict[str, Any]:
        results = []
        for job in jobs:
            if str(job.id) in state["analyses"]:
                result = score_match(
                    candidate, job_facts(job), state["analyses"][str(job.id)], threshold, as_of
                )
                results.append((job.id, result))
        return {"results": results}

    async def persist(state: MatchingState) -> dict[str, Any]:
        if state["skipped"]:
            await session.execute(
                delete(JobMatch).where(
                    JobMatch.candidate_id == request.candidate_id,
                    JobMatch.job_id.in_([uuid.UUID(value) for value in state["skipped"]]),
                )
            )
        for job_id, result in state["results"]:
            row = await session.scalar(
                select(JobMatch).where(
                    JobMatch.candidate_id == request.candidate_id, JobMatch.job_id == job_id
                )
            )
            if row is None:
                row = JobMatch(candidate_id=request.candidate_id, job_id=job_id)
                session.add(row)
            row.score, row.threshold, row.decision = result.score, threshold, result.decision
            row.profile_hash = profile_hash
            row.job_hash = payload["jobs"][str(job_id)]
            row.requirements_hash = request_hash(
                state["analyses"][str(job_id)].model_dump(mode="json")
            )
            row.policy_version, row.as_of, row.execution_id = POLICY_VERSION, as_of, execution.id
            row.explanation = result.model_dump(mode="json")
        await session.flush()
        return {}

    async def finish(state: MatchingState) -> dict[str, Any]:
        decisions: list[str] = [result.decision for _, result in state["results"]]
        execution.status = (
            "PARTIAL"
            if state["errors"] and state["results"]
            else ("FAILED" if state["errors"] else "COMPLETED")
        )
        execution.completed_at = datetime.now(UTC)
        execution.summary = {
            "candidate_id": str(request.candidate_id),
            "threshold": threshold,
            "extractor": request.extractor,
            "policy_version": POLICY_VERSION,
            "counts": {
                key: decisions.count(key)
                for key in [
                    "QUALIFIED",
                    "BELOW_THRESHOLD",
                    "NOT_QUALIFIED",
                    "INELIGIBLE",
                    "REVIEW_REQUIRED",
                ]
            },
            "results": [
                {"job_id": str(job_id), "score": result.score, "decision": result.decision}
                for job_id, result in state["results"]
            ],
            "errors": state["errors"],
            "skipped_fixtures": state["skipped"],
        }
        await session.flush()
        return {}

    graph = StateGraph(MatchingState)
    for name, node in [
        ("extract", extract),
        ("score", score),
        ("persist", persist),
        ("finish", finish),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "extract")
    graph.add_edge("extract", "score")
    graph.add_edge("score", "persist")
    graph.add_edge("persist", "finish")
    graph.add_edge("finish", END)
    await graph.compile().ainvoke({"analyses": {}, "results": [], "errors": [], "skipped": []})
    return {**execution_view(execution), "replayed": False}
