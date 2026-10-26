from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from app.domain.discovery import DiscoveryQuery, Listing, ProviderBatch, SourceConfig
from app.domain.posting_dates import parse_date
from app.integrations.discovery.base import ProviderError
from app.integrations.discovery.http import SafeHTTP
from app.integrations.discovery.parsing import plain_text


def add_listing(batch: ProviderBatch, query: DiscoveryQuery, values: dict[str, Any]) -> None:
    try:
        item = Listing.model_validate(values)
    except (ValidationError, TypeError, ValueError):
        batch.rejected += 1
        return
    if query.posted_within_days is not None:
        now = datetime.now(UTC)
        if (
            item.posted_at is None
            or not now - timedelta(days=query.posted_within_days) <= item.posted_at <= now
        ):
            batch.rejected += 1
            if "OLD_OR_UNDATED_RESULTS_EXCLUDED" not in batch.warnings:
                batch.warnings.append("OLD_OR_UNDATED_RESULTS_EXCLUDED")
            return
    if query.relevant(item.title) and len(batch.items) < query.max_items:
        batch.items.append(item)


class GreenhouseProvider:
    def __init__(self, config: SourceConfig, http: SafeHTTP) -> None:
        self.config, self.http = config, http

    async def collect(self, query: DiscoveryQuery) -> ProviderBatch:
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.config.board}/jobs"
        data = await self.http.json("GET", url, params={"content": "true"})
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ProviderError("INVALID_FEED")
        batch = ProviderBatch()
        for row in data["jobs"][:10000]:
            if not isinstance(row, dict):
                batch.rejected += 1
                continue
            identifier = row.get("id")
            if identifier is None:
                batch.rejected += 1
                continue
            add_listing(
                batch,
                query,
                {
                    "external_id": str(identifier),
                    "posted_at": parse_date(row.get("first_published")),
                    "posting_date_evidence": "first_published"
                    if row.get("first_published")
                    else None,
                    "employer_job_id": str(identifier),
                    "title": row.get("title"),
                    "company": self.config.company,
                    "description": plain_text(str(row.get("content") or "")),
                    "source_url": row.get("absolute_url"),
                    "application_url": row.get("absolute_url"),
                    "location": row["location"].get("name")
                    if isinstance(row.get("location"), dict)
                    else None,
                },
            )
        if len(batch.items) == query.max_items:
            batch.warnings.append("ITEM_LIMIT_REACHED")
        return batch


class LeverProvider:
    def __init__(self, config: SourceConfig, http: SafeHTTP) -> None:
        self.config, self.http = config, http

    async def collect(self, query: DiscoveryQuery) -> ProviderBatch:
        host = "api.eu.lever.co" if self.config.region == "eu" else "api.lever.co"
        url = f"https://{host}/v0/postings/{self.config.board}"
        batch = ProviderBatch()
        # Bounded paging: filter locally, never request an unbounded employer board.
        for page in range(10):
            rows = await self.http.json(
                "GET", url, params={"mode": "json", "skip": page * 100, "limit": 100}
            )
            if not isinstance(rows, list):
                raise ProviderError("INVALID_FEED")
            for row in rows:
                if not isinstance(row, dict):
                    batch.rejected += 1
                    continue
                sections = [str(row.get("descriptionPlain") or row.get("description") or "")]
                raw_sections = row.get("lists") or []
                if not isinstance(raw_sections, list):
                    batch.rejected += 1
                    continue
                for section in raw_sections:
                    if isinstance(section, dict):
                        sections.extend(
                            [str(section.get("text") or ""), str(section.get("content") or "")]
                        )
                sections.append(str(row.get("additionalPlain") or row.get("additional") or ""))
                categories = row.get("categories") or {}
                posted = None
                created = row.get("createdAt")
                if isinstance(created, (int, float)) and not isinstance(created, bool):
                    try:
                        posted = datetime.fromtimestamp(created / 1000, UTC)
                    except (ValueError, OverflowError, OSError):
                        pass
                add_listing(
                    batch,
                    query,
                    {
                        "external_id": row.get("id"),
                        "posted_at": posted,
                        "posting_date_evidence": "createdAt" if posted else None,
                        "employer_job_id": row.get("id"),
                        "title": row.get("text"),
                        "company": self.config.company,
                        "description": plain_text("\n".join(sections)),
                        "source_url": row.get("hostedUrl"),
                        "application_url": row.get("applyUrl"),
                        "location": categories.get("location")
                        if isinstance(categories, dict)
                        else None,
                        "compensation": str(row["salaryRange"])[:500]
                        if row.get("salaryRange")
                        else None,
                        "application_instructions": plain_text(sections[-1])[:20000] or None,
                    },
                )
            if len(batch.items) >= query.max_items:
                batch.warnings.append("ITEM_LIMIT_REACHED")
                break
            if len(rows) < 100:
                break
        else:
            batch.warnings.append("PAGE_LIMIT_REACHED")
        return batch
