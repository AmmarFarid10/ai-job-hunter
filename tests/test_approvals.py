import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.database import get_session
from app.main import app
from app.models import Job
from tests.test_matching_api import setup


async def resume(client: AsyncClient) -> tuple[str, str, str]:
    cid, jid = await setup(client)
    contact = await client.put(
        f"/api/v1/candidates/{cid}/contact", json={"email": "demo@example.com", "confirmed": True}
    )
    assert contact.status_code == 200, contact.text
    run = await client.post("/api/v1/matching/runs", json={"candidate_id": cid, "job_ids": [jid]})
    assert run.status_code == 201
    generated = await client.post(
        "/api/v1/resumes/generations", json={"candidate_id": cid, "job_id": jid}
    )
    assert generated.status_code == 201, generated.text
    return cid, jid, generated.json()["id"]


async def review(client: AsyncClient, version: str) -> dict:
    response = await client.post(
        "/api/v1/approvals",
        json={
            "resume_version_id": version,
            "details": {"method": "manual_handoff", "destination": "https://example.com/jobs/1"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_exact_approval_and_revoke_with_audit(client: AsyncClient):
    cid, jid, vid = await resume(client)
    row = await review(client, vid)
    assert row["can_approve"] and not row["blockers"]
    assert "token=" in row["review_link"] and "token_hash" not in row
    listing = (await client.get("/api/v1/approvals", params={"candidate_id": cid})).json()
    assert "token" not in listing[0] and "token_hash" not in listing[0]
    wrong = await client.post(
        f"/api/v1/approvals/{row['id']}/decision",
        json={"action": "approve", "confirmed": True, "token": "x" * 43},
    )
    assert wrong.status_code == 403
    approved = await client.post(
        f"/api/v1/approvals/{row['id']}/decision",
        json={"action": "approve", "confirmed": True, "token": row["token"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["effective_approved"]
    assert (await client.get(f"/api/v1/resumes/versions/{vid}")).json()["approved"]
    application = (await client.get("/api/v1/applications")).json()[0]
    assert application["state"] == "APPROVED"
    assert [e["to_state"] for e in application["events"]] == [
        "DISCOVERED",
        "MATCHED",
        "RESUME_GENERATED",
        "PENDING_APPROVAL",
        "APPROVED",
    ]
    direct = await client.post(
        f"/api/v1/applications/{application['id']}/transitions", json={"state": "SUBMITTING"}
    )
    assert direct.status_code == 409  # No submission route is enabled in Phase 5.
    revoked = await client.post(
        f"/api/v1/approvals/{row['id']}/decision", json={"action": "revoke", "confirmed": True}
    )
    assert revoked.status_code == 200 and not revoked.json()["effective_approved"]
    assert [e["action"] for e in revoked.json()["events"]] == ["CREATED", "APPROVED", "REVOKED"]
    assert not (await client.get(f"/api/v1/resumes/versions/{vid}")).json()["approved"]


async def test_concurrent_decisions_only_one_wins(client: AsyncClient):
    _, _, vid = await resume(client)
    row = await review(client, vid)
    responses = await asyncio.gather(
        *(
            client.post(
                f"/api/v1/approvals/{row['id']}/decision",
                json={"action": action, "confirmed": True},
            )
            for action in ["approve", "reject"]
        )
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    stored = (await client.get(f"/api/v1/approvals/{row['id']}")).json()
    assert len(stored["events"]) == 2


async def test_superseded_requests_and_immutable_details(client: AsyncClient):
    _, _, vid = await resume(client)
    old = await review(client, vid)
    new = await review(client, vid)
    assert (await client.get(f"/api/v1/approvals/{old['id']}")).json()["status"] == "REVOKED"
    assert (
        await client.post(
            f"/api/v1/approvals/{old['id']}/decision", json={"action": "approve", "confirmed": True}
        )
    ).status_code == 409

    async def tamper():
        async for session in app.dependency_overrides[get_session]():
            await session.execute(
                text("UPDATE approval_requests SET details_hash='changed' WHERE id=:id"),
                {"id": uuid.UUID(new["id"])},
            )

    with pytest.raises(IntegrityError):
        await tamper()


async def test_newer_resume_and_changed_destination_invalidate_approval(client: AsyncClient):
    cid, jid, vid = await resume(client)
    row = await review(client, vid)
    assert (
        await client.post(
            f"/api/v1/approvals/{row['id']}/decision", json={"action": "approve", "confirmed": True}
        )
    ).status_code == 200
    async for session in app.dependency_overrides[get_session]():
        job = await session.get(Job, uuid.UUID(jid))
        job.application_url = "https://example.com/jobs/different"
    changed = (await client.get(f"/api/v1/approvals/{row['id']}")).json()
    assert not changed["effective_approved"] and "JOB_CHANGED" in changed["blockers"]
    await client.post("/api/v1/resumes/generations", json={"candidate_id": cid, "job_id": jid})
    assert (
        "NEWER_RESUME_VERSION_EXISTS"
        in (await client.get(f"/api/v1/approvals/{row['id']}")).json()["blockers"]
    )


async def test_expired_token_and_missing_confirmation(client: AsyncClient, monkeypatch):
    _, _, vid = await resume(client)
    row = await review(client, vid)
    assert (
        await client.post(f"/api/v1/approvals/{row['id']}/decision", json={"action": "approve"})
    ).status_code == 422

    class Future(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(UTC) + timedelta(days=4)

    monkeypatch.setattr("app.services.approvals.datetime", Future)
    assert (
        await client.post(
            f"/api/v1/approvals/{row['id']}/decision", json={"action": "approve", "confirmed": True}
        )
    ).status_code == 409
    assert "EXPIRED" in (await client.get(f"/api/v1/approvals/{row['id']}")).json()["blockers"]


async def test_request_changes_then_new_review(client: AsyncClient):
    _, _, vid = await resume(client)
    row = await review(client, vid)
    assert (
        await client.post(
            f"/api/v1/approvals/{row['id']}/decision",
            json={"action": "request_changes", "confirmed": True},
        )
    ).status_code == 422
    result = await client.post(
        f"/api/v1/approvals/{row['id']}/decision",
        json={
            "action": "request_changes",
            "confirmed": True,
            "reason": "Please select more Python bullets.",
        },
    )
    assert result.status_code == 200 and result.json()["status"] == "CHANGES_REQUESTED"
    new = await review(client, vid)
    assert new["can_approve"]


async def test_review_draft_cannot_be_approved(client: AsyncClient):
    cid, jid = await setup(client)
    async for session in app.dependency_overrides[get_session]():
        job = await session.get(Job, uuid.UUID(jid))
        job.location = "Worldwide Remote"
    await client.post("/api/v1/matching/runs", json={"candidate_id": cid, "job_ids": [jid]})
    generated = await client.post(
        "/api/v1/resumes/generations", json={"candidate_id": cid, "job_id": jid, "mode": "review"}
    )
    assert generated.status_code == 201
    row = await review(client, generated.json()["id"])
    assert (
        not row["can_approve"] and "REVIEW_DRAFT_REQUIRES_QUALIFIED_REGENERATION" in row["blockers"]
    )
    assert (
        await client.post(
            f"/api/v1/approvals/{row['id']}/decision", json={"action": "approve", "confirmed": True}
        )
    ).status_code == 409
    assert (
        await client.post(
            f"/api/v1/approvals/{row['id']}/decision", json={"action": "reject", "confirmed": True}
        )
    ).status_code == 200


async def test_artifact_tamper_and_profile_changes_block_approval(
    client: AsyncClient, tmp_path: Path
):
    from app.config import get_settings

    cid, _, vid = await resume(client)
    row = await review(client, vid)
    path = next(get_settings().storage_dir.glob("tailored/*/resume.docx"))
    path.write_bytes(b"tampered")
    assert (
        "ARTIFACT_INTEGRITY_FAILED"
        in (await client.get(f"/api/v1/approvals/{row['id']}")).json()["blockers"]
    )
    await client.put(
        f"/api/v1/candidates/{cid}/contact",
        json={"email": "changed@example.com", "confirmed": True},
    )
    assert (
        "RESUME_CHANGED_OR_STALE"
        in (await client.get(f"/api/v1/approvals/{row['id']}")).json()["blockers"]
    )
    assert (
        await client.post(
            f"/api/v1/approvals/{row['id']}/decision", json={"action": "approve", "confirmed": True}
        )
    ).status_code == 409


async def test_reports_deduplicate_and_exclude_reviewed_jobs(client: AsyncClient):
    cid, _, vid = await resume(client)
    result = await client.post(
        "/api/v1/notifications/reports",
        json={"candidate_id": cid, "idempotency_key": "first", "deliver": True},
    )
    assert result.status_code == 201, result.text
    report = result.json()
    assert report["status"] == "COMPLETE"
    assert {d["status"] for d in report["deliveries"]} == {"MOCKED"}
    assert len(report["deliveries"]) == 2
    assert len(report["content"]["items"]) == 1
    assert (
        await client.post(
            "/api/v1/notifications/reports",
            json={"candidate_id": cid, "idempotency_key": "first", "deliver": True},
        )
    ).json()["id"] == report["id"]
    second = await client.post(
        "/api/v1/notifications/reports",
        json={"candidate_id": cid, "idempotency_key": "second", "deliver": True},
    )
    assert second.json()["deliveries"] == []
    row = await review(client, vid)
    await client.post(
        f"/api/v1/approvals/{row['id']}/decision", json={"action": "reject", "confirmed": True}
    )
    third = await client.post(
        "/api/v1/notifications/reports",
        json={"candidate_id": cid, "idempotency_key": "third", "deliver": True},
    )
    assert third.json()["content"]["items"] == []


async def test_uncertain_delivery_is_not_retried(client: AsyncClient, monkeypatch):
    from app.integrations.notifications.providers import DeliveryError

    calls = []

    async def uncertain(*args):
        calls.append(args[1])
        raise DeliveryError("TIMEOUT", uncertain=True)

    monkeypatch.setattr("app.services.notifications.send_report", uncertain)
    cid, _, _ = await resume(client)
    payload = {"candidate_id": cid, "idempotency_key": "uncertain", "deliver": True}
    result = await client.post("/api/v1/notifications/reports", json=payload)
    assert result.status_code == 201, result.text
    assert {d["status"] for d in result.json()["deliveries"]} == {"UNKNOWN"}
    assert (await client.post("/api/v1/notifications/reports", json=payload)).status_code == 201
    assert len(calls) == 2  # Once per channel, never retried.


async def test_settings_consent_dashboard_and_preferences(client: AsyncClient):
    cid, _, _ = await resume(client)
    endpoint = f"/api/v1/notifications/settings/{cid}"
    assert not (await client.get(endpoint)).json()["enabled"]
    assert (await client.put(endpoint, json={"enabled": True})).status_code == 422
    saved = await client.put(endpoint, json={"enabled": True, "consent": True})
    assert saved.status_code == 200 and saved.json()["consented_at"]
    assert saved.json()["schedule"] == ["10:00", "20:00"]
    dashboard = await client.get(f"/api/v1/dashboard/{cid}")
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["counts"]["qualified"] == 1
    assert len(dashboard.json()["resumes"]) == 1
    prefs = dashboard.json()["candidate"]["preferences"]
    prefs.pop("id", None)
    prefs.pop("candidate_id", None)
    prefs["match_threshold"] = 99
    updated = await client.put(f"/api/v1/candidates/{cid}/preferences", json=prefs)
    assert updated.status_code == 200, updated.text
    assert (await client.get(f"/api/v1/dashboard/{cid}")).json()["jobs"][0]["match"]["stale"]
    for path in [f"/api/v1/dashboard/{cid}", endpoint, "/api/v1/approvals?candidate_id=" + cid]:
        assert (await client.get(path, headers={"X-API-Key": "wrong"})).status_code == 401


def test_report_timezone_and_schedule():
    from app.services.notifications import report_slot
    from app.services.scheduler import make_scheduler

    assert report_slot(datetime(2026, 10, 21, 15, 0, tzinfo=UTC)) == "2026-10-21:20"
    scheduler = make_scheduler()
    job = scheduler.get_job("twice-daily-reports")
    next_time = job.trigger.get_next_fire_time(None, datetime(2026, 10, 21, 4, 0, tzinfo=UTC))
    assert next_time.hour == 10 and next_time.utcoffset() == timedelta(hours=5)


async def test_outbox_is_durable_before_provider_call(client: AsyncClient, monkeypatch):
    from sqlalchemy import select

    from app.database import get_session
    from app.main import app
    from app.models import NotificationDelivery

    calls = []

    async def inspect_outbox(settings, channel, *args):
        async for worker in app.dependency_overrides[get_session]():
            deliveries = (
                await worker.scalars(
                    select(NotificationDelivery).where(NotificationDelivery.channel == channel)
                )
            ).all()
            assert deliveries and all(row.status == "SENDING" for row in deliveries)
        calls.append(channel)
        return "MOCKED", "durability-test"

    monkeypatch.setattr("app.services.notifications.send_report", inspect_outbox)
    cid, _, _ = await resume(client)
    result = await client.post(
        "/api/v1/notifications/reports", json={"candidate_id": cid, "deliver": True}
    )
    assert result.status_code == 201 and result.json()["status"] == "COMPLETE", result.text
    assert calls == ["email", "whatsapp"]


async def test_preview_cannot_turn_into_delivery_with_same_key(client: AsyncClient):
    cid, _, _ = await resume(client)
    payload = {"candidate_id": cid, "idempotency_key": "preview-only"}
    result = await client.post("/api/v1/notifications/reports", json=payload)
    assert result.json()["status"] == "PREVIEW" and not result.json()["deliveries"]
    assert (
        await client.post("/api/v1/notifications/reports", json={**payload, "deliver": True})
    ).status_code == 409


async def test_scheduler_refreshes_matches_and_deduplicates_slot(client: AsyncClient, monkeypatch):
    from app.models import JobMatch
    from app.services.scheduler import scheduled_reports

    cid, _, _ = await resume(client)
    await client.put(
        f"/api/v1/notifications/settings/{cid}", json={"enabled": True, "consent": True}
    )
    async for worker in app.dependency_overrides[get_session]():
        match = await worker.scalar(select(JobMatch).where(JobMatch.candidate_id == uuid.UUID(cid)))
        match.as_of = datetime.now(UTC).date() - timedelta(days=1)
        engine = worker.bind
    monkeypatch.setattr("app.services.scheduler.get_engine", lambda: engine)
    await scheduled_reports()
    reports = (
        await client.get("/api/v1/notifications/reports", params={"candidate_id": cid})
    ).json()
    assert len(reports) == 1 and reports[0]["content"]["items"]
    assert reports[0]["status"] == "COMPLETE"
    await scheduled_reports()
    assert (
        len(
            (await client.get("/api/v1/notifications/reports", params={"candidate_id": cid})).json()
        )
        == 1
    )


async def test_live_delivery_requires_explicit_consent_and_recipients(
    client: AsyncClient, monkeypatch
):
    from app.config import get_settings

    cid, _, _ = await resume(client)
    monkeypatch.setenv("NOTIFICATION_MODE", "live")
    get_settings.cache_clear()
    assert (
        await client.post(
            "/api/v1/notifications/reports", json={"candidate_id": cid, "deliver": True}
        )
    ).status_code == 409
    assert (
        await client.put(
            f"/api/v1/notifications/settings/{cid}", json={"enabled": True, "consent": True}
        )
    ).status_code == 422
    assert (
        await client.put(
            f"/api/v1/notifications/settings/{cid}",
            json={
                "enabled": True,
                "consent": True,
                "email": "test@example.com",
                "whatsapp_number": "+923001234567",
            },
        )
    ).status_code == 200
    monkeypatch.setenv("NOTIFICATION_MODE", "mock")
    get_settings.cache_clear()
