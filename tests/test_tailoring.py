import io
import unicodedata
import uuid
from pathlib import Path

import pymupdf
import pytest
from docx import Document
from httpx import AsyncClient

from app.config import get_settings
from app.domain.matching import Requirements
from app.domain.tailoring import (
    ResumeSource,
    SourceExperience,
    SourceSkill,
    build_document,
    validate_document,
)
from app.integrations.documents.render import render_resume
from app.integrations.documents.storage import ArtifactError, digest, read_artifact, write_artifacts
from tests.test_matching_api import setup


def source() -> ResumeSource:
    return ResumeSource(
        name="Verified Person",
        education=[],
        skills=[SourceSkill(id="s", name="Python")],
        experiences=[
            SourceExperience(
                id="e",
                title="Backend Engineer",
                employer="Example",
                start_month="2020-03",
                is_current=True,
                bullets=["Mentored 3 colleagues.", "Built Python APIs with 25% lower latency."],
            )
        ],
    )


def test_tailoring_preserves_claims_and_blocks_changes():
    profile = source()
    document = build_document(profile, Requirements(), 1)
    assert document.experiences[0].dates == "Mar 2020 - Present"
    assert document.experiences[0].bullets[0].text in profile.experiences[0].bullets
    assert document.experiences[0].omitted_bullet_indices == [1]
    assert "AWS" not in document.model_dump_json()
    document.summary += " AWS expert."
    with pytest.raises(ValueError):
        validate_document(document, profile, Requirements(), 1)
    profile.experiences[0].is_current = None
    with pytest.raises(ValueError):
        build_document(profile, Requirements(), 5)


def test_both_formats_preserve_content_and_paginate():
    profile = source()
    profile.experiences[0].bullets = [
        f"Built Python APIs for project {i}. " * 35 for i in range(10)
    ]
    output = render_resume(build_document(profile, Requirements(), 10))
    assert output.pages > 1
    assert "Verified Person" in " ".join(
        p.text for p in Document(io.BytesIO(output.docx)).paragraphs
    )
    with pymupdf.open(stream=output.pdf, filetype="pdf") as pdf:
        assert len(pdf) == output.pages
        assert "Verified Person" in unicodedata.normalize("NFKC", pdf[0].get_text())


def test_artifact_integrity_permissions_and_paths(tmp_path: Path):
    version = uuid.uuid4()
    docx, pdf = write_artifacts(tmp_path, version, b"docx", b"pdf")
    assert (tmp_path / docx).stat().st_mode & 0o777 == 0o600
    assert read_artifact(tmp_path, pdf, digest(b"pdf")) == b"pdf"
    with pytest.raises(FileExistsError):
        write_artifacts(tmp_path, version, b"new", b"new")
    (tmp_path / pdf).write_bytes(b"tampered")
    with pytest.raises(ArtifactError):
        read_artifact(tmp_path, pdf, digest(b"pdf"))
    with pytest.raises(ArtifactError):
        read_artifact(tmp_path, "../outside", digest(b"x"))


async def ready(client: AsyncClient) -> dict[str, str]:
    cid, jid = await setup(client)
    result = await client.post(
        "/api/v1/matching/runs", json={"candidate_id": cid, "job_ids": [jid]}
    )
    assert result.status_code == 201, result.text
    return {"candidate_id": cid, "job_id": jid, "idempotency_key": "tailoring-test"}


async def test_generation_downloads_replay_history_and_integrity(client: AsyncClient):
    payload = await ready(client)
    result = await client.post("/api/v1/resumes/generations", json=payload)
    assert result.status_code == 201, result.text
    row = result.json()
    assert row["version"] == 1 and not row["approved"] and row["inputs_current"]
    assert "MISSING_CONFIRMED_CONTACT_EMAIL" in row["document_data"]["warnings"]
    assert (await client.post("/api/v1/resumes/generations", json=payload)).json()["id"] == row[
        "id"
    ]
    for format, magic in [("pdf", b"%PDF"), ("docx", b"PK")]:
        downloaded = await client.get(row["downloads"][format])
        assert downloaded.status_code == 200 and downloaded.content.startswith(magic)
        assert digest(downloaded.content) == row[format + "_sha256"]
    second = await client.post(
        "/api/v1/resumes/generations", json={**payload, "idempotency_key": "second"}
    )
    assert second.json()["version"] == 2
    history = await client.get(
        "/api/v1/resumes/versions",
        params={"candidate_id": payload["candidate_id"], "job_id": payload["job_id"]},
    )
    assert [item["version"] for item in history.json()] == [2, 1]
    artifact = next(get_settings().storage_dir.glob("tailored/*/resume.pdf"))
    artifact.write_bytes(b"tamper")
    failed = [await client.get(item["downloads"]["pdf"]) for item in history.json()]
    assert sorted(r.status_code for r in failed) == [200, 409]
    assert (await client.get("/api/v1/applications")).json() == []


async def test_review_draft_is_explicit_and_unapproved(client: AsyncClient):
    cid, jid = await setup(client)
    # Worldwide work eligibility is unknown, so matching must retain the review gate.
    from app.database import get_session
    from app.main import app
    from app.models import Job

    async for session in app.dependency_overrides[get_session]():
        job = await session.get(Job, uuid.UUID(jid))
        job.location = "Worldwide - Remote"
    run = await client.post("/api/v1/matching/runs", json={"candidate_id": cid, "job_ids": [jid]})
    assert run.status_code == 201
    payload = {"candidate_id": cid, "job_id": jid}
    blocked = await client.post("/api/v1/resumes/generations", json=payload)
    assert blocked.status_code == 409, blocked.text
    draft = await client.post("/api/v1/resumes/generations", json={**payload, "mode": "review"})
    assert draft.status_code == 201, draft.text
    assert draft.json()["status"] == "DRAFT_REVIEW" and not draft.json()["approved"]


async def test_history_survives_profile_changes_and_database_blocks_mutation(client: AsyncClient):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from app.database import get_session
    from app.main import app

    payload = await ready(client)
    row = (await client.post("/api/v1/resumes/generations", json=payload)).json()
    original = (await client.get(row["downloads"]["pdf"])).content

    async def mutate() -> None:
        async for session in app.dependency_overrides[get_session]():
            await session.execute(
                text("UPDATE resume_versions SET content_hash = 'changed' WHERE id = :id"),
                {"id": uuid.UUID(row["id"])},
            )

    with pytest.raises(IntegrityError):
        await mutate()
    changed = await client.put(
        f"/api/v1/candidates/{payload['candidate_id']}/profile",
        json={"name": "Changed Name", "confirmed": True, "skills": ["Python"]},
    )
    assert changed.status_code == 200
    history = await client.get(f"/api/v1/resumes/versions/{row['id']}")
    assert not history.json()["inputs_current"]
    assert history.json()["document_data"]["document"]["name"] == "Verified Demo"
    assert (await client.get(row["downloads"]["pdf"])).content == original
    assert (await client.post("/api/v1/resumes/generations", json=payload)).status_code == 409
    assert (
        await client.post(
            "/api/v1/resumes/generations", json={**payload, "idempotency_key": "changed"}
        )
    ).status_code == 409


async def test_concurrent_generations_allocate_distinct_versions(client: AsyncClient):
    import asyncio

    payload = await ready(client)
    responses = await asyncio.gather(
        *(
            client.post(
                "/api/v1/resumes/generations", json={**payload, "idempotency_key": f"parallel-{i}"}
            )
            for i in range(3)
        )
    )
    assert all(result.status_code == 201 for result in responses)
    assert sorted(result.json()["version"] for result in responses) == [1, 2, 3]


async def test_unverified_children_are_excluded(client: AsyncClient):
    from app.database import get_session
    from app.main import app
    from app.models import CandidateSkill

    payload = await ready(client)
    async for session in app.dependency_overrides[get_session]():
        session.add(
            CandidateSkill(
                candidate_id=uuid.UUID(payload["candidate_id"]),
                name="Unverified Technology",
                normalized_name="unverified technology",
                verified=False,
            )
        )
    await client.post(
        "/api/v1/matching/runs",
        json={"candidate_id": payload["candidate_id"], "job_ids": [payload["job_id"]]},
    )
    row = await client.post("/api/v1/resumes/generations", json=payload)
    assert row.status_code == 201, row.text
    assert "Unverified Technology" not in str(row.json()["document_data"]["document"])
    assert "UNVERIFIED_PROFILE_RECORDS_EXCLUDED" in row.json()["document_data"]["warnings"]


async def test_pdf_preview_checks_integrity_and_page_bounds(client: AsyncClient):
    payload = await ready(client)
    row = (await client.post("/api/v1/resumes/generations", json=payload)).json()
    path = f"/api/v1/resumes/versions/{row['id']}/preview/1"
    response = await client.get(path)
    assert response.status_code == 200 and response.content.startswith(b"\x89PNG\r\n")
    assert (await client.get(path[:-1] + "999")).status_code == 404
    assert (await client.get(path, headers={"X-API-Key": "wrong"})).status_code == 401
