"""Exercise real user sessions; the maintenance API key must not mask isolation bugs."""

import os
import uuid

import pymupdf
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.database import get_session
from app.main import app
from app.models import AdminAudit, Candidate, CandidateSkill, WorkspaceAccount
from tests.test_matching_api import setup


async def register(client, email):
    response = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": email.split("@")[0],
            "email": email,
            "password": "fictional-private-password-123",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["user"]["role"] == "USER"
    return response.json(), {"X-API-Key": "", "X-Owner-Session": response.json()["token"]}


async def test_users_private_reads_writes_and_deduplication(client):
    # The shared maintenance workspace is also invisible to public signups.
    legacy = (await client.post("/api/v1/candidates", json={"name": "Legacy private"})).json()["id"]
    one, h1 = await register(client, "first@example.com")
    two, h2 = await register(client, "second@example.com")
    assert (await client.get("/api/v1/candidates", headers=h1)).json() == []
    assert (await client.get("/api/v1/candidates/" + legacy, headers=h1)).status_code == 404
    c1 = (await client.post("/api/v1/candidates", headers=h1, json={"name": "Private One"})).json()[
        "id"
    ]
    c2 = (await client.post("/api/v1/candidates", headers=h2, json={"name": "Private Two"})).json()[
        "id"
    ]
    payload = {
        "title": "Python Engineer",
        "company": "Fictional Employer",
        "description": "Python APIs",
        "source_name": "manual",
        "source_url": "https://example.com/jobs/123",
        "linkedin_job_id": "123",
    }
    j1 = (await client.post("/api/v1/jobs", headers=h1, json=payload)).json()["job"]["id"]
    duplicate = (await client.post("/api/v1/jobs", headers=h1, json=payload)).json()
    assert not duplicate["created"] and duplicate["job"]["id"] == j1
    j2response = await client.post("/api/v1/jobs", headers=h2, json=payload)
    assert j2response.status_code == 201, j2response.text
    j2 = j2response.json()["job"]["id"]
    assert j1 != j2
    assert [c["id"] for c in (await client.get("/api/v1/candidates", headers=h2)).json()] == [c2]
    assert [j["id"] for j in (await client.get("/api/v1/jobs", headers=h2)).json()] == [j2]
    for path in [
        f"candidates/{c1}",
        f"dashboard/{c1}",
        f"jobs/{j1}",
        f"matching/jobs/{j1}/requirements",
        f"notifications/settings/{c1}",
        f"candidates/{c1}/resumes",
    ]:
        assert (await client.get("/api/v1/" + path, headers=h2)).status_code == 404, path
    for cid, jid, h in [(c1, j1, h2), (c2, j1, h2), (c1, j2, h1)]:
        r = await client.post(
            "/api/v1/applications",
            headers=h,
            json={"candidate_id": cid, "job_id": jid, "idempotency_key": "same-private-key"},
        )
        assert r.status_code == 404, r.text
    for cid, jid, h in [(c1, j1, h1), (c2, j2, h2)]:
        r = await client.post(
            "/api/v1/applications",
            headers=h,
            json={"candidate_id": cid, "job_id": jid, "idempotency_key": "same-private-key"},
        )
        assert r.status_code == 201, r.text
    assert len((await client.get("/api/v1/applications", headers=h1)).json()) == 1
    assert (
        await client.put(
            f"/api/v1/candidates/{c1}/preferences", headers=h2, json={"roles": ["stolen"]}
        )
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/matching/runs", headers=h2, json={"candidate_id": c1, "job_ids": [j2]}
        )
    ).status_code == 404
    assert (
        await client.post("/api/v1/notifications/reports", headers=h2, json={"candidate_id": c1})
    ).status_code == 404
    assert (
        await client.get(
            "/api/v1/candidates", headers={**h2, "X-Workspace-User": one["user"]["id"]}
        )
    ).status_code == 403
    assert (await client.get("/api/v1/admin/users", headers=h2)).status_code == 403
    assert (await client.get("/api/v1/admin/audit", headers=h2)).status_code == 403


async def test_admin_bootstrap_scope_and_append_only_audit(client):
    one, h1 = await register(client, "administrator@example.com")
    two, h2 = await register(client, "regular@example.com")
    candidate = (
        await client.post("/api/v1/candidates", headers=h2, json={"name": "Second private"})
    ).json()["id"]
    assert (
        await client.post("/api/v1/admin/bootstrap", headers=h1, json={"setup_key": "wrong"})
    ).status_code == 403
    promoted = await client.post(
        "/api/v1/admin/bootstrap", headers=h1, json={"setup_key": os.environ["API_KEY"]}
    )
    assert promoted.status_code == 200 and promoted.json()["user"]["role"] == "ADMIN"
    assert not (await client.get("/api/v1/auth/status")).json()["admin_bootstrap_available"]
    assert (
        await client.post(
            "/api/v1/admin/bootstrap", headers=h2, json={"setup_key": os.environ["API_KEY"]}
        )
    ).status_code == 409
    assert (await client.get("/api/v1/candidates", headers=h1)).json() == []
    scoped = {**h1, "X-Workspace-User": two["user"]["id"]}
    assert (await client.get("/api/v1/candidates/" + candidate, headers=scoped)).status_code == 200
    created = await client.post(
        "/api/v1/candidates", headers=scoped, json={"name": "Admin managed"}
    )
    assert created.status_code == 201
    assert len((await client.get("/api/v1/candidates", headers=h2)).json()) == 2
    assert (await client.get("/api/v1/candidates", headers=h1)).json() == []
    audit = (await client.get("/api/v1/admin/audit", headers=h1)).json()
    assert len(audit) == 3
    assert all(row["actor_account_id"] == one["user"]["id"] for row in audit)
    assert any(
        row["target_account_id"] == two["user"]["id"] and row["method"] == "POST" for row in audit
    )
    assert len((await client.get("/api/v1/admin/users", headers=h1)).json()) == 2
    async for session in app.dependency_overrides[get_session]():
        async with session.begin_nested():
            with pytest.raises(DBAPIError):
                await session.execute(delete(AdminAudit))
            await session.rollback()
    # Revocation takes effect for existing sessions, not just new logins.
    async for session in app.dependency_overrides[get_session]():
        account = await session.get(WorkspaceAccount, uuid.UUID(one["user"]["id"]))
        account.role = "USER"
    assert (await client.get("/api/v1/candidates", headers=scoped)).status_code == 403


async def test_orm_counts_bulk_writes_and_database_cross_owner_constraints(client):
    one, h1 = await register(client, "a@example.com")
    two, h2 = await register(client, "b@example.com")
    c1 = (await client.post("/api/v1/candidates", headers=h1, json={"name": "One"})).json()["id"]
    c2 = (await client.post("/api/v1/candidates", headers=h2, json={"name": "Two"})).json()["id"]
    async for session in app.dependency_overrides[get_session]():
        session.info.clear()
        assert await session.scalar(select(func.count()).select_from(Candidate)) == 0
        session.info["owner_id"] = uuid.UUID(one["user"]["id"])
        assert await session.scalar(select(func.count()).select_from(Candidate)) == 1
        assert await session.get(Candidate, uuid.UUID(c2)) is None
        await session.execute(update(Candidate).values(name="Scoped rename"))
        await session.execute(delete(CandidateSkill))
    assert (await client.get("/api/v1/candidates/" + c2, headers=h2)).json()["name"] == "Two"
    async for session in app.dependency_overrides[get_session]():
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(
                    CandidateSkill(
                        candidate_id=uuid.UUID(c2),
                        owner_account_id=uuid.UUID(one["user"]["id"]),
                        name="Python",
                        normalized_name="python",
                    )
                )
                await session.flush()
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.execute(
                    update(Candidate)
                    .where(Candidate.id == uuid.UUID(c1))
                    .values(owner_account_id=uuid.UUID(two["user"]["id"]))
                )


async def test_private_resume_artifacts_and_execution_replay(client):
    one, h1 = await register(client, "resume1@example.com")
    two, h2 = await register(client, "resume2@example.com")
    client.headers.update(h1)
    cid, jid = await setup(client)
    matched = await client.post(
        "/api/v1/matching/runs",
        json={"candidate_id": cid, "job_ids": [jid], "idempotency_key": "shared-key"},
    )
    assert matched.status_code == 201, matched.text
    run_id = matched.json()["id"]
    generated = await client.post(
        "/api/v1/resumes/generations",
        json={"candidate_id": cid, "job_id": jid, "idempotency_key": "shared-generation"},
    )
    assert generated.status_code == 201, generated.text
    vid = generated.json()["id"]
    pdf = pymupdf.open()
    pdf.new_page().insert_text((30, 30), "Fictional private master resume")
    upload = await client.post(
        f"/api/v1/candidates/{cid}/resumes",
        files={"file": ("resume.pdf", pdf.tobytes(), "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    draft = upload.json()["id"]
    for path in [
        f"resumes/versions/{vid}",
        f"resumes/versions/{vid}/download/pdf",
        f"resumes/versions/{vid}/download/docx",
        f"resumes/versions/{vid}/preview/0",
        f"candidates/{cid}/resumes/{draft}",
        f"candidates/{cid}/resumes/{draft}/download",
        f"matching/runs/{run_id}",
    ]:
        assert (await client.get("/api/v1/" + path, headers=h2)).status_code == 404, path
    assert (
        await client.get(f"/api/v1/resumes/versions/{vid}/download/pdf", headers=h1)
    ).status_code == 200
    client.headers.update(h2)
    cid2, jid2 = await setup(client)
    assert cid != cid2 and jid != jid2
    again = await client.post(
        "/api/v1/matching/runs",
        json={"candidate_id": cid2, "job_ids": [jid2], "idempotency_key": "shared-key"},
    )
    assert again.status_code == 201, again.text
    assert again.json()["id"] != run_id
    again = await client.post(
        "/api/v1/resumes/generations",
        json={"candidate_id": cid2, "job_id": jid2, "idempotency_key": "shared-generation"},
    )
    assert again.status_code == 201, again.text
    assert again.json()["id"] != vid
    for h in [h1, h2]:
        discovery = await client.post(
            "/api/v1/discovery/runs",
            headers=h,
            json={"sources": ["mock"], "idempotency_key": "shared-discovery"},
        )
        assert discovery.status_code == 201, discovery.text
    ids1 = {i["id"] for i in (await client.get("/api/v1/discovery/items", headers=h1)).json()}
    ids2 = {i["id"] for i in (await client.get("/api/v1/discovery/items", headers=h2)).json()}
    assert ids1 and ids2 and not ids1.intersection(ids2)
    assert (
        await client.get("/api/v1/discovery/items/" + next(iter(ids1)), headers=h2)
    ).status_code == 404


async def test_notification_worker_and_scheduler_keep_workspace(client, monkeypatch):
    from app.models import AgentExecution, NotificationReport
    from app.services.scheduler import scheduled_reports

    first, h1 = await register(client, "report1@example.com")
    second, h2 = await register(client, "report2@example.com")
    candidates = []
    for h in (h1, h2):
        client.headers.update(h)
        cid, jid = await setup(client)
        candidates.append(cid)
        response = await client.put(
            "/api/v1/notifications/settings/" + cid,
            json={
                "enabled": True,
                "email_enabled": True,
                "whatsapp_enabled": False,
                "email": "fictional@example.com",
                "consent": True,
            },
        )
        assert response.status_code == 200, response.text
        response = await client.post(
            "/api/v1/notifications/reports", json={"candidate_id": cid, "deliver": True}
        )
        assert response.status_code == 201, response.text
    async for session in app.dependency_overrides[get_session]():
        engine = session.bind
    monkeypatch.setattr("app.services.scheduler.get_engine", lambda: engine)
    await scheduled_reports()
    async for session in app.dependency_overrides[get_session]():
        reports = (await session.scalars(select(NotificationReport))).all()
        assert len(reports) == 4
        executions = (await session.scalars(select(AgentExecution))).all()
        assert len(executions) == 2
        for execution in executions:
            owner = execution.owner_account_id
            assert owner in {uuid.UUID(first["user"]["id"]), uuid.UUID(second["user"]["id"])}
            # Each scheduler execution has precisely the job in its own workspace.
            assert len(execution.summary["results"]) == 1


async def test_server_gmail_source_hidden_from_regular_users(client, monkeypatch):
    from pathlib import Path

    from app.integrations.discovery.email import GmailAlertProvider
    from app.integrations.discovery.http import SafeHTTP
    from app.integrations.discovery.mock import MockProvider
    from app.integrations.discovery.registry import ProviderRegistry, get_registry

    registry = ProviderRegistry(
        {
            "owner-gmail": GmailAlertProvider(
                SafeHTTP({"gmail.googleapis.com"}), Path("/nonexistent/private-token.json"), "query"
            ),
            "mock": MockProvider(),
        },
        [
            {"name": "owner-gmail", "kind": "gmail", "configured": True},
            {"name": "mock", "kind": "mock", "configured": True},
        ],
    )
    app.dependency_overrides[get_registry] = lambda: registry
    try:
        _, h = await register(client, "gmail-private@example.com")
        providers = (await client.get("/api/v1/discovery/providers", headers=h)).json()
        assert [p["name"] for p in providers] == ["mock"]
        response = await client.post(
            "/api/v1/discovery/runs", headers=h, json={"sources": ["owner-gmail"]}
        )
        assert response.status_code == 422 and "UNKNOWN_OR_DISABLED_SOURCE" in response.text
    finally:
        app.dependency_overrides.pop(get_registry, None)


async def test_admin_initializer_uses_salted_hash_and_does_not_reset_password(
    client, monkeypatch, capsys
):
    from app.admin import initialize
    from app.config import get_settings
    from app.domain.auth import password_valid

    monkeypatch.setenv("ADMIN_EMAIL", "configured-admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "fictional-initial-admin-password")
    get_settings.cache_clear()
    async for session in app.dependency_overrides[get_session]():
        engine = session.bind
    monkeypatch.setattr("app.admin.get_engine", lambda: engine)
    await initialize()
    async for session in app.dependency_overrides[get_session]():
        account = await session.scalar(select(WorkspaceAccount))
        assert account.role == "ADMIN"
        assert password_valid("fictional-initial-admin-password", account.password_hash)
        original = account.password_hash
    monkeypatch.setenv("ADMIN_PASSWORD", "different-future-password")
    get_settings.cache_clear()
    await initialize()
    async for session in app.dependency_overrides[get_session]():
        assert (await session.scalar(select(WorkspaceAccount))).password_hash == original
    assert "fictional-initial-admin-password" not in capsys.readouterr().out
    assert (await client.get("/api/v1/auth/status")).json()["admin_bootstrap_available"] is False
    forbidden = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Forged",
            "email": "forged@example.com",
            "password": "fictional-safe-password",
            "role": "ADMIN",
        },
    )
    assert forbidden.status_code == 422


async def test_approval_tokens_do_not_authorize_another_workspace(client):
    from tests.test_approvals import resume, review

    _, h1 = await register(client, "approval-owner@example.com")
    _, h2 = await register(client, "approval-other@example.com")
    client.headers.update(h1)
    cid, jid, vid = await resume(client)
    approval = await review(client, vid)
    assert approval["can_approve"]
    assert (await client.get("/api/v1/approvals/" + approval["id"], headers=h2)).status_code == 404
    forbidden = await client.post(
        "/api/v1/approvals/" + approval["id"] + "/decision",
        headers=h2,
        json={"action": "approve", "confirmed": True, "token": approval["token"]},
    )
    assert forbidden.status_code == 404
    allowed = await client.post(
        "/api/v1/approvals/" + approval["id"] + "/decision",
        json={"action": "approve", "confirmed": True, "token": approval["token"]},
    )
    assert allowed.status_code == 200 and allowed.json()["effective_approved"]
    assert (
        await client.get("/api/v1/approvals", params={"candidate_id": cid}, headers=h2)
    ).json() == []
