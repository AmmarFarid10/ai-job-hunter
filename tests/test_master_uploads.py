import uuid

from httpx import AsyncClient

from app.config import get_settings
from tests.test_api import candidate
from tests.test_pdf import make_pdf


async def test_master_history_download_integrity_and_candidate_binding(client: AsyncClient):
    cid = await candidate(client)
    other = await candidate(client)
    prefix = f"/api/v1/candidates/{cid}/resumes"
    assert (await client.get(prefix)).json() == []
    pdf = make_pdf()
    draft = (
        await client.post(prefix, files={"file": ("master.pdf", pdf, "application/pdf")})
    ).json()
    history = await client.get(prefix)
    assert history.status_code == 200 and history.json()[0]["id"] == draft["id"]
    assert not history.json()[0]["reviewed_at"]
    assert (await client.get(prefix + f"/{draft['id']}/download")).content == pdf
    assert (
        await client.get(f"/api/v1/candidates/{other}/resumes/{draft['id']}/download")
    ).status_code == 404
    profile = (await client.get(f"/api/v1/candidates/{cid}")).json()
    assert not profile["verified"] and not profile["skills"]
    path = next(p for p in get_settings().storage_dir.glob("*.pdf"))
    path.write_bytes(b"tampered")
    assert (await client.get(prefix + f"/{draft['id']}/download")).status_code == 409
    assert (await client.get(prefix, headers={"X-API-Key": "wrong"})).status_code == 401


async def test_discovery_items_can_be_filtered_by_provider(client: AsyncClient):
    from app.database import get_session
    from app.main import app
    from app.models import AgentExecution, DiscoveryItem

    async for session in app.dependency_overrides[get_session]():
        execution = AgentExecution(agent_name="job_discovery", status="COMPLETED", summary={})
        session.add(execution)
        await session.flush()
        for provider in ["linkedin-tavily", "another-source"]:
            session.add(
                DiscoveryItem(
                    execution_id=execution.id,
                    provider=provider,
                    external_id=uuid.uuid4().hex,
                    status="REVIEW_REQUIRED",
                    payload={"title": "Python opportunity"},
                )
            )
    rows = (await client.get("/api/v1/discovery/items?provider=linkedin-tavily")).json()
    assert len(rows) == 1 and rows[0]["provider"] == "linkedin-tavily"
    assert (await client.get("/api/v1/discovery/items?provider=unknown")).json() == []
