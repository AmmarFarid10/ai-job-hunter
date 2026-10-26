import asyncio
import os
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.main import app
from tests.test_pdf import make_pdf

JOB: dict[str, Any] = {
    "title": "Senior Python Engineer",
    "company": "Example Co",
    "description": "Build distributed Python APIs with FastAPI.",
    "source_name": "mock",
    "source_url": "https://example.com/jobs/42",
    "employer_job_id": "42",
    "application_url": "https://example.com/apply/42",
}


async def candidate(client: AsyncClient) -> str:
    result = await client.post("/api/v1/candidates", json={"name": "Unverified Demo"})
    assert result.status_code == 201, result.text
    return str(result.json()["id"])


async def job(client: AsyncClient) -> str:
    result = await client.post("/api/v1/jobs", json=JOB)
    assert result.status_code == 201, result.text
    return str(result.json()["job"]["id"])


async def test_health_and_authentication() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        assert (await http.get("/health")).json() == {"status": "ok"}
        assert (await http.get("/api/v1/candidates")).status_code == 401
        assert (await http.get("/api/v1/jobs", headers={"X-API-Key": "bad"})).status_code == 401


async def test_profile_review_and_pdf(client: AsyncClient) -> None:
    cid = await candidate(client)
    path = f"/api/v1/candidates/{cid}"
    assert (await client.get(path)).json()["verified"] is False
    upload = await client.post(path + "/resumes", files={"file": ("../../resume.pdf", make_pdf())})
    assert upload.status_code == 201, upload.text
    draft = upload.json()
    assert draft["suggestions"]["verified"] is False
    assert (await client.get(path)).json()["skills"] == []
    assert (await client.get(path + "/resumes/" + draft["id"])).status_code == 200
    profile = {
        "name": "Confirmed Demo",
        "confirmed": True,
        "skills": ["Python"],
        "experiences": [{"employer": "Confirmed Employer", "title": "Engineer"}],
        "education": [{"institution": "Confirmed School", "degree": "BS"}],
    }
    url = path + "/resumes/" + draft["id"] + "/confirm"
    assert (await client.post(url, json={**profile, "confirmed": False})).status_code == 422
    confirmation = await client.post(url, json=profile)
    assert confirmation.status_code == 200, confirmation.text
    assert confirmation.json()["verified"] is True
    assert confirmation.json()["skills"] == [{"name": "Python", "verified": True}]
    assert (await client.post(url, json=profile)).status_code == 409
    assert (
        await client.put(path + "/profile", json={**profile, "skills": ["FastAPI"]})
    ).status_code == 200
    assert (await client.get(path)).json()["skills"][0]["name"] == "FastAPI"


async def test_invalid_and_oversize_uploads(client: AsyncClient) -> None:
    cid = await candidate(client)
    url = f"/api/v1/candidates/{cid}/resumes"
    assert (await client.post(url, files={"file": ("fake.pdf", b"junk")})).status_code == 422
    response = await client.post(url, files={"file": ("big.pdf", b"x" * (10485760 + 1))})
    assert response.status_code == 413


async def test_missing_records_and_validation(client: AsyncClient) -> None:
    assert (await client.get(f"/api/v1/candidates/{uuid.uuid4()}")).status_code == 404
    assert (
        await client.post("/api/v1/jobs", json={**JOB, "source_url": "file:///tmp"})
    ).status_code == 422
    assert (await client.get("/api/v1/jobs?limit=99999")).status_code == 422


async def test_cross_source_deduplication(client: AsyncClient) -> None:
    jid = await job(client)
    second = {
        **JOB,
        "source_name": "linkedin-alert",
        "source_url": "https://linkedin.com/jobs/view/9999",
    }
    result = await client.post("/api/v1/jobs", json=second)
    assert result.status_code == 201, result.text
    assert result.json()["created"] is False
    assert result.json()["job"]["id"] == jid
    assert len(result.json()["job"]["sources"]) == 2
    # An ID from this observation now resolves even with another description.
    third = {
        **JOB,
        "source_url": "https://another.example/jobs/9999",
        "description": "Updated description",
        "linkedin_job_id": "9999",
    }
    assert (await client.post("/api/v1/jobs", json=third)).json()["job"]["id"] == jid
    assert len((await client.get("/api/v1/jobs")).json()) == 1


async def test_fuzzy_is_review_only(client: AsyncClient) -> None:
    jid = await job(client)
    other = {
        **JOB,
        "description": "A separate vacancy for another team.",
        "source_url": "https://example.com/jobs/43",
        "employer_job_id": "43",
        "application_url": "https://example.com/apply/43",
    }
    result = await client.post("/api/v1/jobs", json=other)
    assert result.json()["created"] is True
    assert jid in result.json()["possible_duplicate_ids"]
    assert len((await client.get("/api/v1/jobs")).json()) == 2


async def test_identity_conflict_is_not_merged(client: AsyncClient) -> None:
    await job(client)
    result = await client.post("/api/v1/jobs", json={**JOB, "employer_job_id": "different"})
    assert result.status_code == 409
    assert len((await client.get("/api/v1/jobs")).json()) == 1


async def test_concurrent_discovery(client: AsyncClient) -> None:
    results = await asyncio.gather(*[client.post("/api/v1/jobs", json=JOB) for _ in range(5)])
    assert all(row.status_code == 201 for row in results), [row.text for row in results]
    assert len({row.json()["job"]["id"] for row in results}) == 1
    assert sum(row.json()["created"] for row in results) == 1


async def test_applications_idempotency_and_states(client: AsyncClient) -> None:
    cid, jid = await candidate(client), await job(client)
    payload = {"candidate_id": cid, "job_id": jid, "idempotency_key": "request-1"}
    result = await client.post("/api/v1/applications", json=payload)
    assert result.status_code == 201, result.text
    aid = result.json()["id"]
    replay = await client.post("/api/v1/applications", json=payload)
    assert replay.json()["id"] == aid
    duplicate = await client.post(
        "/api/v1/applications", json={**payload, "idempotency_key": "request-2"}
    )
    assert duplicate.status_code == 409, duplicate.text
    url = f"/api/v1/applications/{aid}/transitions"
    assert (await client.post(url, json={"state": "SUBMITTED"})).status_code == 409
    for state in ["MATCHED", "RESUME_GENERATED", "PENDING_APPROVAL"]:
        response = await client.post(url, json={"state": state, "reason": "Owner review"})
        assert response.status_code == 200, response.text
    assert (await client.post(url, json={"state": "APPROVED"})).status_code == 409
    stored = (await client.get(f"/api/v1/applications/{aid}")).json()
    assert stored["state"] == "PENDING_APPROVAL"
    assert len(stored["events"]) == 4
    assert (await client.post(url, json={"state": "REJECTED"})).status_code == 200
    assert (await client.post(url, json={"state": "MATCHED"})).status_code == 409


async def test_concurrent_applications_are_unique(client: AsyncClient) -> None:
    cid, jid = await candidate(client), await job(client)
    responses = await asyncio.gather(
        *[
            client.post(
                "/api/v1/applications",
                json={
                    "candidate_id": cid,
                    "job_id": jid,
                },
            )
            for _ in range(4)
        ]
    )
    assert sorted(row.status_code for row in responses) == [201, 409, 409, 409]


async def test_database_directly_rejects_duplicates(client: AsyncClient) -> None:
    cid, jid = await candidate(client), await job(client)
    result = await client.post("/api/v1/applications", json={"candidate_id": cid, "job_id": jid})
    assert result.status_code == 201
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO applications "
                        "(id, candidate_id, job_id, state, idempotency_key) "
                        "VALUES (:id, :cid, :jid, 'DISCOVERED', :key)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "cid": uuid.UUID(cid),
                        "jid": uuid.UUID(jid),
                        "key": str(uuid.uuid4()),
                    },
                )
    finally:
        await engine.dispose()


async def test_shared_hiring_post_does_not_merge_distinct_jobs(client: AsyncClient) -> None:
    shared = {
        **JOB,
        "employer_job_id": None,
        "source_url": "https://www.linkedin.com/posts/recruiter-multiple-openings",
        "application_url": "https://example.com/careers",
    }
    first = await client.post("/api/v1/jobs", json=shared)
    second = await client.post(
        "/api/v1/jobs",
        json={
            **shared,
            "description": "A different team is hiring a senior Python engineer.",
        },
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["job"]["id"] != second.json()["job"]["id"]
    assert second.json()["created"] is True


async def test_request_limit_before_multipart_parsing() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post(
            "/api/v1/candidates", content=b"{}", headers={"Content-Length": "999999999"}
        )
        assert response.status_code == 413


async def test_observed_employer_identity_is_preserved(client: AsyncClient) -> None:
    first = {**JOB, "employer_job_id": None}
    jid = (await client.post("/api/v1/jobs", json=first)).json()["job"]["id"]
    observed = await client.post("/api/v1/jobs", json=JOB)
    assert observed.json()["job"]["id"] == jid
    assert observed.json()["job"]["employer_job_id"] == "42"
    conflict = await client.post("/api/v1/jobs", json={**JOB, "employer_job_id": "other"})
    assert conflict.status_code == 409


async def test_conflicting_existing_identity_bridge(client: AsyncClient) -> None:
    first_id = await job(client)
    other = {
        **JOB,
        "description": "Separate position",
        "employer_job_id": "43",
        "source_url": "https://example.com/jobs/43",
        "application_url": "https://example.com/apply/43",
    }
    second = await client.post("/api/v1/jobs", json=other)
    assert second.status_code == 201
    bridge = await client.post(
        "/api/v1/jobs",
        json={
            **JOB,
            "source_url": other["source_url"],
        },
    )
    assert bridge.status_code == 409
    assert len((await client.get("/api/v1/jobs")).json()) == 2
    assert (await client.get(f"/api/v1/jobs/{first_id}")).status_code == 200
