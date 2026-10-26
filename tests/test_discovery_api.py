import asyncio
from types import SimpleNamespace
from typing import Any

from httpx import AsyncClient

from app.domain.discovery import DiscoveryQuery, Listing, ProviderBatch
from app.integrations.discovery.base import ProviderError
from app.integrations.discovery.mock import MockProvider
from app.integrations.discovery.registry import ProviderRegistry, get_registry
from app.main import app
from tests.test_discovery_providers import ALERT


class FailingProvider:
    async def collect(self, query: DiscoveryQuery) -> ProviderBatch:
        raise ProviderError("HTTP_503")


class ExplodingProvider:
    async def collect(self, query: DiscoveryQuery) -> ProviderBatch:
        raise RuntimeError("SECRET_REMOTE_TOKEN_AND_INSTRUCTIONS")


class DuplicateFeed:
    async def collect(self, query: DiscoveryQuery) -> ProviderBatch:
        return ProviderBatch(
            items=[
                Listing(
                    external_id="other-observation",
                    title="Senior Python Backend Engineer (DEMO)",
                    company="Fictional Discovery Demo Employer",
                    description="Source variant",
                    source_url="https://another.example/jobs/phase2-demo-python",
                    employer_job_id="phase2-demo-python",
                )
            ]
        )


async def test_discovery_default_and_replay(client: AsyncClient) -> None:
    providers = await client.get("/api/v1/discovery/providers")
    assert providers.status_code == 200
    assert providers.json()[0]["name"] == "mock"
    payload = {"sources": ["mock"], "idempotency_key": "run-1"}
    result = await client.post("/api/v1/discovery/runs", json=payload)
    assert result.status_code == 201, result.text
    run = result.json()
    assert run["status"] == "COMPLETED"
    assert run["summary"]["counts"]["created"] == 1
    assert run["summary"]["counts"]["review_required"] == 1
    assert run["replayed"] is False
    replay = await client.post("/api/v1/discovery/runs", json=payload)
    assert replay.json()["id"] == run["id"] and replay.json()["replayed"] is True
    assert len((await client.get("/api/v1/discovery/runs")).json()) == 1
    assert (await client.get("/api/v1/discovery/runs/" + run["id"])).json()["status"] == "COMPLETED"
    rerun = await client.post(
        "/api/v1/discovery/runs", json={**payload, "idempotency_key": "run-2"}
    )
    assert rerun.json()["summary"]["counts"]["seen"] == 2
    changed = await client.post(
        "/api/v1/discovery/runs", json={**payload, "search_terms": ["FastAPI"]}
    )
    assert changed.status_code == 409
    assert len((await client.get("/api/v1/jobs")).json()) == 1
    assert (await client.get("/api/v1/applications")).json() == []


async def test_unknown_source_and_validation(client: AsyncClient) -> None:
    assert (
        await client.post("/api/v1/discovery/runs", json={"sources": ["unknown"]})
    ).status_code == 422
    assert (
        await client.post("/api/v1/discovery/runs", json={"max_items": 10000})
    ).status_code == 422
    assert (
        await client.post("/api/v1/discovery/runs", json={"sources": ["mock", "mock"]})
    ).status_code == 422
    assert (await client.get("/api/v1/discovery/runs")).json() == []
    assert (await client.get("/api/v1/discovery/items?status=UNKNOWN")).status_code == 422


async def test_cross_provider_canonical_identity(client: AsyncClient) -> None:
    registry = ProviderRegistry({"mock": MockProvider(), "other": DuplicateFeed()})
    app.dependency_overrides[get_registry] = lambda: registry
    result = await client.post("/api/v1/discovery/runs", json={"sources": ["mock", "other"]})
    assert result.status_code == 201, result.text
    counts = result.json()["summary"]["counts"]
    assert counts["created"] == counts["deduplicated"] == 1
    jobs = (await client.get("/api/v1/jobs")).json()
    assert len(jobs) == 1 and len(jobs[0]["sources"]) == 2


async def test_failed_provider_does_not_rollback_success(client: AsyncClient) -> None:
    registry = ProviderRegistry(
        {"mock": MockProvider(), "bad": FailingProvider(), "boom": ExplodingProvider()}
    )
    app.dependency_overrides[get_registry] = lambda: registry
    result = await client.post("/api/v1/discovery/runs", json={"sources": ["bad", "mock", "boom"]})
    assert result.status_code == 201, result.text
    assert result.json()["status"] == "PARTIAL"
    assert result.json()["summary"]["counts"]["created"] == 1
    assert "SECRET_REMOTE" not in result.text
    assert {error["code"] for error in result.json()["summary"]["errors"]} == {
        "HTTP_503",
        "INVALID_PROVIDER_RESPONSE",
    }


async def test_all_failures_are_persisted_and_replayable(client: AsyncClient) -> None:
    registry = ProviderRegistry({"bad": FailingProvider()})
    app.dependency_overrides[get_registry] = lambda: registry
    payload = {"sources": ["bad"], "idempotency_key": "failed-run"}
    first = await client.post("/api/v1/discovery/runs", json=payload)
    assert first.status_code == 201 and first.json()["status"] == "FAILED"
    second = await client.post("/api/v1/discovery/runs", json=payload)
    assert second.json()["replayed"] is True
    assert second.json()["id"] == first.json()["id"]


async def test_review_import_and_dismiss(client: AsyncClient) -> None:
    await client.post("/api/v1/discovery/runs", json={})
    items = (await client.get("/api/v1/discovery/items?status=REVIEW_REQUIRED")).json()
    assert len(items) == 1
    item_id = items[0]["id"]
    assert (await client.get("/api/v1/discovery/items/" + item_id)).status_code == 200
    payload = {
        "title": "Python Engineer",
        "company": "Explicitly Reviewed Employer",
        "source_name": "owner-reviewed",
        "source_url": items[0]["payload"]["source_url"],
        "description": "Owner reviewed role and employer from source.",
        "application_instructions": "Manual handoff to the employer.",
    }
    result = await client.post(f"/api/v1/discovery/items/{item_id}/import", json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["job"]["application_instructions"] == payload["application_instructions"]
    assert (
        await client.post(f"/api/v1/discovery/items/{item_id}/import", json=payload)
    ).status_code == 409
    assert (await client.post(f"/api/v1/discovery/items/{item_id}/dismiss")).status_code == 409
    assert (await client.get("/api/v1/discovery/items/" + item_id)).json()["reviewed_at"]


async def test_email_import_no_automatic_jobs_and_safe_replay(client: AsyncClient) -> None:
    payload = {"raw_email": ALERT, "idempotency_key": "email-1"}
    result = await client.post("/api/v1/discovery/import-email", json=payload)
    assert result.status_code == 201, result.text
    assert result.json()["summary"]["counts"]["review_required"] == 1
    assert (await client.get("/api/v1/jobs")).json() == []
    items = (await client.get("/api/v1/discovery/items")).json()
    assert items[0]["payload"]["linkedin_job_id"] == "12345"
    assert "user@example.invalid" not in str(items)
    replay = await client.post("/api/v1/discovery/import-email", json=payload)
    assert replay.json()["replayed"] is True
    changed = await client.post(
        "/api/v1/discovery/import-email", json={**payload, "raw_email": ALERT + "changed"}
    )
    assert changed.status_code == 409
    item_id = items[0]["id"]
    assert (await client.post(f"/api/v1/discovery/items/{item_id}/dismiss")).status_code == 200
    assert (await client.post(f"/api/v1/discovery/items/{item_id}/dismiss")).status_code == 409
    rerun = await client.post(
        "/api/v1/discovery/import-email", json={**payload, "idempotency_key": "email-2"}
    )
    assert rerun.json()["summary"]["counts"]["seen"] == 1
    assert (await client.get("/api/v1/discovery/items")).json()[0]["status"] == "DISMISSED"


async def test_concurrent_discovery_is_bounded(client: AsyncClient) -> None:
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    class WaitingProvider:
        async def collect(self, query: DiscoveryQuery) -> ProviderBatch:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return ProviderBatch()

    app.dependency_overrides[get_registry] = lambda: ProviderRegistry({"wait": WaitingProvider()})
    payload = {"sources": ["wait"], "idempotency_key": "concurrent-run"}
    task = asyncio.create_task(client.post("/api/v1/discovery/runs", json=payload))
    try:
        await asyncio.wait_for(started.wait(), 3)
        competing = await client.post("/api/v1/discovery/runs", json=payload)
        assert competing.status_code == 409
        another = await client.post(
            "/api/v1/discovery/runs", json={**payload, "idempotency_key": "another-key"}
        )
        assert another.status_code == 409
    finally:
        release.set()
    assert (await task).status_code == 201 and calls == 1
    replay = await client.post("/api/v1/discovery/runs", json=payload)
    assert replay.json()["replayed"] is True and calls == 1


async def test_conflict_observation_preserved_without_losing_other_jobs(
    client: AsyncClient,
) -> None:
    class ConflictProvider:
        async def collect(self, query: DiscoveryQuery) -> ProviderBatch:
            base = (await MockProvider().collect(query)).items[0]
            conflict = base.model_copy(
                update={"external_id": "conflicting", "employer_job_id": "different"}
            )
            return ProviderBatch(items=[base, conflict])

    app.dependency_overrides[get_registry] = lambda: ProviderRegistry(
        {"conflict": ConflictProvider()}
    )
    result = await client.post("/api/v1/discovery/runs", json={"sources": ["conflict"]})
    assert result.status_code == 201, result.text
    assert result.json()["status"] == "PARTIAL"
    assert result.json()["summary"]["counts"]["conflict"] == 1
    conflicts = (await client.get("/api/v1/discovery/items?status=CONFLICT")).json()
    assert len(conflicts) == 1 and conflicts[0]["job_id"] is None
    assert len((await client.get("/api/v1/jobs")).json()) == 1


async def test_provider_timeout_is_safe_and_persisted(
    client: AsyncClient, monkeypatch: Any
) -> None:
    class SlowProvider:
        async def collect(self, query: DiscoveryQuery) -> ProviderBatch:
            await asyncio.sleep(5)
            return ProviderBatch()

    app.dependency_overrides[get_registry] = lambda: ProviderRegistry({"slow": SlowProvider()})
    monkeypatch.setattr(
        "app.api.discovery.get_settings",
        lambda: SimpleNamespace(environment="test", discovery_timeout_seconds=0.01),
    )
    result = await client.post("/api/v1/discovery/runs", json={"sources": ["slow"]})
    assert result.status_code == 201, result.text
    assert result.json()["status"] == "FAILED"
    assert result.json()["summary"]["errors"][0]["code"] == "PROVIDER_TIMEOUT"


async def test_maximum_items_is_a_run_limit_across_sources(client):
    calls = []

    class Provider:
        async def collect(self, query):
            calls.append(query.max_items)
            return ProviderBatch(
                items=[
                    Listing(
                        external_id=str(i),
                        title="Python Engineer",
                        company="Fictional",
                        source_url=f"https://example.com/jobs/{i}",
                        requires_review=True,
                    )
                    for i in range(query.max_items)
                ]
            )

    app.dependency_overrides[get_registry] = lambda: ProviderRegistry(
        {"first": Provider(), "second": Provider()}
    )
    response = await client.post(
        "/api/v1/discovery/runs",
        json={"sources": ["first", "second"], "search_terms": ["Python"], "max_items": 2},
    )
    assert response.status_code == 201, response.text
    assert len(response.json()["summary"]["results"]) == 2
    assert calls == [2]
    assert any(
        warning["code"] == "RUN_ITEM_LIMIT_REACHED"
        for warning in response.json()["summary"]["warnings"]
    )
