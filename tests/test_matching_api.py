import asyncio
from typing import Any

from httpx import AsyncClient

from app.domain.matching import Requirements
from app.integrations.matching.rules import RulesExtractor
from tests.test_api import candidate


async def setup(client: AsyncClient) -> tuple[str, str]:
    cid = await candidate(client)
    response = await client.put(
        f"/api/v1/candidates/{cid}/profile",
        json={
            "name": "Verified Demo",
            "location": "Lahore, Pakistan",
            "confirmed": True,
            "skills": ["Python", "FastAPI"],
            "experiences": [
                {
                    "title": "Senior Backend Engineer",
                    "employer": "Demo",
                    "start_month": "2015-01",
                    "is_current": True,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    job = await client.post(
        "/api/v1/jobs",
        json={
            "title": "Senior Python Backend Engineer",
            "company": "Example",
            "description": "Python and FastAPI required. 5 years of professional experience.",
            "location": "Pakistan - Remote",
            "source_name": "test",
            "source_url": "https://example.com/jobs/match-1",
        },
    )
    assert job.status_code == 201, job.text
    return cid, job.json()["job"]["id"]


async def test_matching_persists_explanations_and_replays(client: AsyncClient):
    cid, jid = await setup(client)
    payload = {"candidate_id": cid, "job_ids": [jid], "idempotency_key": "matching-test"}
    result = await client.post("/api/v1/matching/runs", json=payload)
    assert result.status_code == 201, result.text
    assert result.json()["summary"]["counts"]["QUALIFIED"] == 1
    replay = await client.post("/api/v1/matching/runs", json=payload)
    assert replay.json()["replayed"] and replay.json()["id"] == result.json()["id"]
    matches = await client.get(f"/api/v1/matching/candidates/{cid}/matches?qualified_only=true")
    assert matches.status_code == 200, matches.text
    stored = matches.json()[0]
    assert stored["score"] == 100 and stored["qualified"] and not stored["stale"]
    assert sum(stored["explanation"]["components"].values()) == stored["score"]
    assert stored["explanation"]["industry_years_lower_bound"] > 11
    assert (await client.get(f"/api/v1/matching/candidates/{cid}/matches/{jid}")).json()[
        "qualified"
    ]
    assert len((await client.get("/api/v1/matching/runs")).json()) == 1
    assert (await client.get("/api/v1/matching/runs/" + result.json()["id"])).status_code == 200
    assert (await client.get("/api/v1/applications")).json() == []


async def test_matching_rejects_unconfirmed_profiles_and_invalid_inputs(client: AsyncClient):
    cid = await candidate(client)
    assert (
        await client.post("/api/v1/matching/runs", json={"candidate_id": cid})
    ).status_code == 409
    assert (
        await client.post("/api/v1/matching/runs", json={"candidate_id": cid, "threshold": 101})
    ).status_code == 422
    assert (
        await client.post(
            "/api/v1/matching/runs", json={"candidate_id": cid, "extractor": "openai"}
        )
    ).status_code == 422
    assert (await client.get("/api/v1/matching/runs")).json() == []


async def test_profile_change_invalidates_results_and_replay(client: AsyncClient):
    cid, jid = await setup(client)
    payload = {"candidate_id": cid, "job_ids": [jid], "idempotency_key": "freshness-test"}
    first = await client.post("/api/v1/matching/runs", json=payload)
    assert first.status_code == 201
    update = await client.put(
        f"/api/v1/candidates/{cid}/profile",
        json={
            "name": "Updated Demo",
            "location": "Lahore, Pakistan",
            "confirmed": True,
            "skills": ["Python"],
        },
    )
    assert update.status_code == 200
    assert (await client.get(f"/api/v1/matching/candidates/{cid}/matches/{jid}")).json()["stale"]
    assert (
        await client.get(f"/api/v1/matching/candidates/{cid}/matches?qualified_only=true")
    ).json() == []
    assert (await client.post("/api/v1/matching/runs", json=payload)).status_code == 409
    rerun = await client.post(
        "/api/v1/matching/runs", json={**payload, "idempotency_key": "fresh-run"}
    )
    assert rerun.status_code == 201
    assert len((await client.get(f"/api/v1/matching/candidates/{cid}/matches")).json()) == 1


async def test_review_requirements_evidence_and_staleness(client: AsyncClient):
    cid, jid = await setup(client)
    await client.post("/api/v1/matching/runs", json={"candidate_id": cid, "job_ids": [jid]})
    analysis = await client.get(f"/api/v1/matching/jobs/{jid}/requirements")
    assert analysis.status_code == 200
    requirements = analysis.json()["requirements"]
    requirements["skills"] = [
        {"skill": "python", "importance": "required", "evidence": "Senior Python Backend Engineer"}
    ]
    reviewed = await client.put(
        f"/api/v1/matching/jobs/{jid}/requirements",
        json={"confirmed": True, "requirements": requirements},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["method"] == "owner" and reviewed.json()["reviewed_at"]
    assert (await client.get(f"/api/v1/matching/candidates/{cid}/matches/{jid}")).json()["stale"]
    requirements["skills"] = [
        {"skill": "aws", "importance": "required", "evidence": "Python and FastAPI required."}
    ]
    invalid = await client.put(
        f"/api/v1/matching/jobs/{jid}/requirements",
        json={"confirmed": True, "requirements": requirements},
    )
    assert invalid.status_code == 422


async def test_matching_concurrency_lock(client: AsyncClient, monkeypatch: Any):
    cid, jid = await setup(client)
    started, release = asyncio.Event(), asyncio.Event()
    original = RulesExtractor.extract

    async def wait(self, title, description):
        started.set()
        await release.wait()
        return await original(self, title, description)

    monkeypatch.setattr(RulesExtractor, "extract", wait)
    payload = {"candidate_id": cid, "job_ids": [jid], "idempotency_key": "concurrent"}
    task = asyncio.create_task(client.post("/api/v1/matching/runs", json=payload))
    try:
        await asyncio.wait_for(started.wait(), 3)
        assert (await client.post("/api/v1/matching/runs", json=payload)).status_code == 409
    finally:
        release.set()
    assert (await task).status_code == 201


async def test_invalid_extraction_is_persisted_as_safe_error(client: AsyncClient, monkeypatch: Any):
    cid, jid = await setup(client)

    async def bad(self, title, description):
        return Requirements.model_validate(
            {"skills": [{"skill": "aws", "importance": "required", "evidence": "Never in source"}]}
        )

    monkeypatch.setattr(RulesExtractor, "extract", bad)
    result = await client.post(
        "/api/v1/matching/runs", json={"candidate_id": cid, "job_ids": [jid]}
    )
    assert result.status_code == 201, result.text
    assert result.json()["status"] == "FAILED"
    assert result.json()["summary"]["errors"][0]["code"] == "UNSUPPORTED_REQUIREMENT_EVIDENCE"
    assert (await client.get(f"/api/v1/matching/candidates/{cid}/matches")).json() == []


async def test_preferences_update_preserves_facts_and_invalidates_matches(client: AsyncClient):
    cid, jid = await setup(client)
    await client.post("/api/v1/matching/runs", json={"candidate_id": cid, "job_ids": [jid]})
    update = await client.put(
        f"/api/v1/matching/candidates/{cid}/preferences",
        json={
            "confirmed": True,
            "preferences": {
                "match_threshold": 95,
                "minimum_annual_salary": "100000",
                "salary_currency": "USD",
                "open_to_relocation": False,
            },
        },
    )
    assert update.status_code == 200, update.text
    profile = (await client.get(f"/api/v1/candidates/{cid}")).json()
    assert len(profile["skills"]) == 2 and len(profile["experiences"]) == 1 and profile["verified"]
    assert profile["preferences"]["match_threshold"] == 95
    assert (await client.get(f"/api/v1/matching/candidates/{cid}/matches/{jid}")).json()["stale"]
    invalid = await client.put(
        f"/api/v1/matching/candidates/{cid}/preferences",
        json={"confirmed": True, "preferences": {"minimum_annual_salary": "100000"}},
    )
    assert invalid.status_code == 422


async def test_fictional_source_is_skipped_without_application_url(client: AsyncClient):
    cid, _ = await setup(client)
    job = await client.post(
        "/api/v1/jobs",
        json={
            "title": "Python Engineer demo",
            "company": "Fictional Employer",
            "description": "Python required.",
            "location": "Pakistan",
            "source_name": "mock",
            "source_url": "https://example.invalid/jobs/old-seed",
        },
    )
    assert job.status_code == 201
    result = await client.post("/api/v1/matching/runs", json={"candidate_id": cid})
    assert result.status_code == 201, result.text
    assert result.json()["summary"]["skipped_fixtures"] == [job.json()["job"]["id"]]
    assert len((await client.get(f"/api/v1/matching/candidates/{cid}/matches")).json()) == 1
