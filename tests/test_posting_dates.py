from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.database import get_session
from app.domain.discovery import Listing
from app.domain.posting_dates import parse_date, posting_date, recent_posting
from app.integrations.discovery.search import recent_linkedin_listing
from app.main import app
from app.models import AgentExecution, DiscoveryItem
from app.services.discovery import store_listing

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "recent"),
    [
        ("Posted 2 hours ago", True),
        ("Posted 6 days ago", True),
        ("Posted 7 days ago", True),
        ("Posted 8 days ago", False),
        ("Posted 2 weeks ago", False),
        ("Posted 1 month ago", False),
        ("Posted on 2026-10-20", True),
        ("Reposted 2 days ago", True),
        ("Posted on October 20, 2026", True),
        ("2 days ago · Python Engineer", True),
        ("We built APIs 2 days ago", False),
        ("Updated yesterday", False),
        ("", False),
        ("Posted on 2027-10-20", False),
        ("Posted on 2026-02-30", False),
    ],
)
def test_posting_evidence(text, recent):
    posted, _ = posting_date({}, text, NOW)
    assert recent_posting(posted, NOW) is recent


def test_cutoff_and_crawl_or_update_metadata_do_not_imply_posting():
    assert recent_posting(NOW - timedelta(days=7), NOW)
    assert not recent_posting(NOW - timedelta(days=7, microseconds=1), NOW)
    assert not recent_posting(NOW + timedelta(seconds=1), NOW)
    row = {
        "url": "https://linkedin.com/jobs/view/123",
        "title": "Python Engineer",
        "published_date": NOW.isoformat(),
        "page_age": NOW.isoformat(),
        "age": "1 hour ago",
    }
    assert recent_linkedin_listing(row, "No posting date", NOW) is None
    assert recent_linkedin_listing(row, "Posted 2 months ago", NOW) is None
    item = recent_linkedin_listing(row, "Posted 3 days ago", NOW)
    assert item and item.posted_at == NOW - timedelta(days=3) and item.requires_review
    assert posting_date({"datePosted": "2026-10-20"}, "", NOW)[0] == datetime(
        2026, 10, 20, tzinfo=UTC
    )
    assert parse_date("2026-10-20T18:00:00+05:00") == datetime(2026, 10, 20, 13, tzinfo=UTC)


async def test_saved_recent_filter_is_applied_before_pagination_and_keeps_history(client):
    now = datetime.now(UTC)
    async for session in app.dependency_overrides[get_session]():
        run = AgentExecution(agent_name="job_discovery", status="COMPLETED", summary={})
        session.add(run)
        await session.flush()
        for index, posted in enumerate(
            [now - timedelta(days=2), now - timedelta(days=8), None, now + timedelta(days=1)]
        ):
            payload = {
                "title": "Python lead",
                "source_url": f"https://linkedin.com/jobs/view/{index}",
            }
            if posted:
                payload["posted_at"] = posted.isoformat()
            session.add(
                DiscoveryItem(
                    execution_id=run.id,
                    provider="linkedin-tavily",
                    external_id=str(index),
                    status="REVIEW_REQUIRED",
                    payload=payload,
                )
            )
    all_rows = (await client.get("/api/v1/discovery/items?provider=linkedin-tavily")).json()
    assert len(all_rows) == 4
    recent = (
        await client.get(
            "/api/v1/discovery/items?provider=linkedin-tavily&posted_within_days=7&limit=1"
        )
    ).json()
    assert len(recent) == 1 and recent[0]["external_id"] == "0"
    assert (await client.get("/api/v1/discovery/items?posted_within_days=7&offset=1")).json() == []
    assert (await client.get("/api/v1/discovery/items?posted_within_days=30")).status_code == 422
    async for session in app.dependency_overrides[get_session]():
        run = await session.scalar(select(AgentExecution))
        result = await store_listing(
            session,
            run.id,
            "linkedin-tavily",
            Listing(
                external_id="2",
                title="New snippet",
                source_url="https://linkedin.com/jobs/view/2",
                description="Posted 1 day ago",
                posted_at=now - timedelta(days=1),
                posting_date_evidence="Posted 1 day ago",
                requires_review=True,
            ),
        )
        assert result["outcome"] == "seen"
    rows = (await client.get("/api/v1/discovery/items?posted_within_days=7")).json()
    assert len(rows) == 2
    refreshed = next(row for row in rows if row["external_id"] == "2")
    assert refreshed["payload"]["title"] == "Python lead"  # Preserve the original observation.
    assert refreshed["payload"]["posting_date_evidence"] == "Posted 1 day ago"


@pytest.mark.parametrize("kind", ["tavily", "brave"])
async def test_search_providers_reject_old_undated_and_future_even_if_page_is_recent(kind):
    import httpx
    from pydantic import SecretStr

    from app.domain.discovery import DiscoveryQuery
    from app.integrations.discovery.search import BraveSearchProvider, TavilySearchProvider
    from tests.test_discovery_providers import safe_http

    def handler(request):
        rows = []
        for index, text in enumerate(
            [
                "Posted 1 day ago",
                "Posted 12 days ago",
                "No posting date",
                "Posted on 2099-01-01",
                "Posted 9999 years ago",
                "Posted 30+ days ago",
            ]
        ):
            rows.append(
                {
                    "url": f"https://linkedin.com/jobs/view/{index + 100}",
                    "title": "Python Engineer",
                    "content": text,
                    "description": text,
                    "published_date": datetime.now(UTC).isoformat(),
                }
            )
        return httpx.Response(
            200, json={"results": rows} if kind == "tavily" else {"web": {"results": rows}}
        )

    cls = TavilySearchProvider if kind == "tavily" else BraveSearchProvider
    host = "api.tavily.com" if kind == "tavily" else "api.search.brave.com"
    batch = await cls(safe_http(handler, {host}), SecretStr("fictional-key")).collect(
        DiscoveryQuery(search_terms=["Python"])
    )
    assert [item.external_id for item in batch.items] == ["100"]
    assert batch.rejected == 5
    assert batch.items[0].posted_at and batch.items[0].posting_date_evidence == "Posted 1 day ago"


async def test_company_feeds_use_original_posting_dates_not_updated_dates():
    import httpx

    from app.domain.discovery import DiscoveryQuery, SourceConfig
    from app.integrations.discovery.feeds import GreenhouseProvider, LeverProvider
    from tests.test_discovery_providers import safe_http

    now = datetime.now(UTC)
    query = DiscoveryQuery(search_terms=["Python"], posted_within_days=7)

    def greenhouse(request):
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 1,
                        "title": "Python Engineer",
                        "absolute_url": "https://example.com/jobs/1",
                        "first_published": now.isoformat(),
                        "content": "Python",
                    },
                    {
                        "id": 2,
                        "title": "Python Engineer",
                        "absolute_url": "https://example.com/jobs/2",
                        "updated_at": now.isoformat(),
                        "content": "Python",
                    },
                    {
                        "id": 3,
                        "title": "Python Engineer",
                        "absolute_url": "https://example.com/jobs/3",
                        "first_published": (now - timedelta(days=20)).isoformat(),
                        "content": "Python",
                    },
                ]
            },
        )

    batch = await GreenhouseProvider(
        SourceConfig(name="company", kind="greenhouse", company="Fictional", board="fixture"),
        safe_http(greenhouse),
    ).collect(query)
    assert [item.external_id for item in batch.items] == ["1"] and batch.rejected == 2

    def lever(request):
        return httpx.Response(
            200,
            json=[
                {
                    "id": "recent",
                    "text": "Python Engineer",
                    "hostedUrl": "https://example.com/jobs/recent",
                    "createdAt": int(now.timestamp() * 1000),
                },
                {
                    "id": "old",
                    "text": "Python Engineer",
                    "hostedUrl": "https://example.com/jobs/old",
                    "createdAt": int((now - timedelta(days=30)).timestamp() * 1000),
                },
            ],
        )

    batch = await LeverProvider(
        SourceConfig(name="company", kind="lever", company="Fictional", board="fixture"),
        safe_http(lever),
    ).collect(query)
    assert [item.external_id for item in batch.items] == ["recent"] and batch.rejected == 1
