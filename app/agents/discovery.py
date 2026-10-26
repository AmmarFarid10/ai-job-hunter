import asyncio
import time
from datetime import UTC, datetime
from typing import Any, TypedDict

from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.discovery import DiscoveryQuery, DiscoveryRequest, Listing
from app.integrations.discovery.base import ProviderError
from app.integrations.discovery.registry import ProviderRegistry
from app.services.discovery import execution_view, reserve_run, store_listing


class DiscoveryState(TypedDict):
    listings: list[tuple[str, Listing]]
    errors: list[dict[str, str]]
    warnings: list[dict[str, str]]
    rejected: int
    results: list[dict[str, Any]]


async def run_discovery(
    session: AsyncSession,
    request: DiscoveryRequest,
    registry: ProviderRegistry,
    budget_seconds: int,
) -> dict[str, Any]:
    # Check replay before provider config, so saved runs remain readable if config changes.
    execution, fresh = await reserve_run(
        session, request.idempotency_key, request.model_dump(exclude={"idempotency_key"})
    )
    if not fresh:
        return {**execution_view(execution), "replayed": True}
    try:
        providers = registry.select(request.sources)
    except ProviderError as exc:
        raise HTTPException(422, exc.code) from exc
    from app.services.quotas import reserve_usage

    await reserve_usage(session, "discovery")
    query = DiscoveryQuery(
        search_terms=request.search_terms,
        max_items=request.max_items,
        posted_within_days=request.posted_within_days,
    )

    async def collect(state: DiscoveryState) -> dict[str, Any]:
        listings: list[tuple[str, Listing]] = []
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        rejected = 0
        deadline = time.monotonic() + budget_seconds
        for name, provider in providers.items():
            remaining_items = query.max_items - len(listings)
            if remaining_items <= 0:
                warnings.append({"provider": name, "code": "RUN_ITEM_LIMIT_REACHED"})
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                errors.append({"provider": name, "code": "RUN_BUDGET_EXHAUSTED"})
                continue
            try:
                batch = await asyncio.wait_for(
                    provider.collect(query.model_copy(update={"max_items": remaining_items})),
                    timeout=remaining,
                )
                listings.extend((name, item) for item in batch.items[:remaining_items])
                rejected += batch.rejected
                warnings.extend({"provider": name, "code": code} for code in batch.warnings)
            except TimeoutError:
                errors.append({"provider": name, "code": "PROVIDER_TIMEOUT"})
            except ProviderError as exc:
                errors.append({"provider": name, "code": exc.code})
            except Exception:
                # Raw exceptions can include secrets; persist only a fixed error code.
                errors.append({"provider": name, "code": "INVALID_PROVIDER_RESPONSE"})
        return {"listings": listings, "errors": errors, "warnings": warnings, "rejected": rejected}

    async def normalize(state: DiscoveryState) -> dict[str, Any]:
        seen: set[tuple[str, str]] = set()
        listings = []
        for name, listing in state["listings"]:
            key = (name, listing.external_id)
            if key not in seen:
                listings.append((name, listing))
                seen.add(key)
        return {"listings": listings}

    async def persist(state: DiscoveryState) -> dict[str, Any]:
        results = []
        for name, listing in state["listings"]:
            results.append(await store_listing(session, execution.id, name, listing))
        return {"results": results}

    async def finish(state: DiscoveryState) -> dict[str, Any]:
        outcomes = [row["outcome"] for row in state["results"]]
        execution.summary = {
            "sources": request.sources,
            "counts": {
                key: outcomes.count(key)
                for key in ["created", "deduplicated", "seen", "review_required", "conflict"]
            },
            "rejected": state["rejected"],
            "results": state["results"],
            "errors": state["errors"],
            "warnings": state["warnings"],
        }
        execution.status = (
            "FAILED"
            if len(state["errors"]) == len(providers)
            else "PARTIAL"
            if state["errors"] or "conflict" in outcomes or state["rejected"]
            else "COMPLETED"
        )
        execution.completed_at = datetime.now(UTC)
        await session.flush()
        return {}

    graph = StateGraph(DiscoveryState)
    graph.add_node("collect", collect)
    graph.add_node("normalize", normalize)
    graph.add_node("persist", persist)
    graph.add_node("finish", finish)
    graph.add_edge(START, "collect")
    graph.add_edge("collect", "normalize")
    graph.add_edge("normalize", "persist")
    graph.add_edge("persist", "finish")
    graph.add_edge("finish", END)
    await graph.compile().ainvoke(
        {"listings": [], "errors": [], "warnings": [], "rejected": 0, "results": []}
    )
    return {**execution_view(execution), "replayed": False}
