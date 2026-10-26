from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr, ValidationError

from app.domain.discovery import DiscoveryQuery, Listing, ProviderBatch
from app.domain.posting_dates import posting_date, recent_posting
from app.integrations.discovery.base import ProviderError
from app.integrations.discovery.http import SafeHTTP
from app.integrations.discovery.parsing import linkedin_listing


def recent_linkedin_listing(row: dict[str, Any], description: str, now: datetime) -> Listing | None:
    item = linkedin_listing(str(row.get("url") or ""), str(row.get("title") or ""), description)
    if item is None:
        return None
    posted, evidence = posting_date(row, item.description, now)
    if not recent_posting(posted, now):
        return None
    item.posted_at, item.posting_date_evidence = posted, evidence
    return item


class BraveSearchProvider:
    def __init__(self, http: SafeHTTP, api_key: SecretStr | None) -> None:
        self.http, self.api_key = http, api_key

    async def collect(self, query: DiscoveryQuery) -> ProviderBatch:
        if not self.api_key:
            raise ProviderError("BRAVE_KEY_NOT_CONFIGURED")
        now = datetime.now(UTC)
        batch = ProviderBatch(warnings=["LAST_7_DAYS_ONLY_OLD_OR_UNDATED_RESULTS_EXCLUDED"])
        if len(query.search_terms) > 3:
            batch.warnings.append("SEARCH_TERM_LIMIT_REACHED")
        # Bound requests/cost and keep all retrieved content out of prompts or tool instructions.
        for term in query.search_terms[:3]:
            data = await self.http.json(
                "GET",
                "https://api.search.brave.com/res/v1/web/search",
                params={
                    "q": f'"{term}" (site:linkedin.com/jobs/view OR site:linkedin.com/posts)',
                    "count": min(20, query.max_items),
                    "freshness": "pw",
                },
                headers={
                    "X-Subscription-Token": self.api_key.get_secret_value(),
                    "Accept": "application/json",
                },
            )
            if not isinstance(data, dict) or not isinstance(data.get("web", {}), dict):
                raise ProviderError("INVALID_SEARCH_RESPONSE")
            results = data.get("web", {}).get("results", [])
            if not isinstance(results, list):
                raise ProviderError("INVALID_SEARCH_RESPONSE")
            for row in results:
                if not isinstance(row, dict):
                    batch.rejected += 1
                    continue
                try:
                    item = recent_linkedin_listing(row, str(row.get("description") or ""), now)
                except (ValueError, ValidationError):
                    item = None
                if item is None:
                    batch.rejected += 1
                elif all(existing.external_id != item.external_id for existing in batch.items):
                    batch.items.append(item)
                if len(batch.items) >= query.max_items:
                    batch.warnings.append("ITEM_LIMIT_REACHED")
                    return batch
        batch.warnings.append("SEARCH_SNIPPETS_REQUIRE_REVIEW")
        return batch


class TavilySearchProvider:
    """Bounded basic searches; LinkedIn snippets always require owner review."""

    def __init__(self, http: SafeHTTP, api_key: SecretStr | None) -> None:
        self.http, self.api_key = http, api_key

    async def collect(self, query: DiscoveryQuery) -> ProviderBatch:
        if not self.api_key:
            raise ProviderError("TAVILY_KEY_NOT_CONFIGURED")
        now = datetime.now(UTC)
        batch = ProviderBatch(
            warnings=[
                "SEARCH_SNIPPETS_REQUIRE_REVIEW",
                "LAST_7_DAYS_ONLY_OLD_OR_UNDATED_RESULTS_EXCLUDED",
            ]
        )
        if len(query.search_terms) > 3:
            batch.warnings.append("SEARCH_TERM_LIMIT_REACHED")
        # Basic depth and disabled auto parameters bound this to at most three basic calls.
        # POST searches are not retried: a timeout can still consume API credits.
        for term in query.search_terms[:3]:
            data = await self.http.json(
                "POST",
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {self.api_key.get_secret_value()}"},
                json_body={
                    "query": f'"{term}" jobs hiring Pakistan remote worldwide '
                    "(site:linkedin.com/jobs/view OR site:linkedin.com/posts)",
                    "search_depth": "basic",
                    "auto_parameters": False,
                    "max_results": min(20, query.max_items),
                    "topic": "general",
                    "time_range": "week",
                    "include_published_date": True,
                    "filter_by_published_date": True,
                    "include_domains": ["linkedin.com"],
                    "include_answer": False,
                    "include_raw_content": False,
                    "include_images": False,
                },
            )
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                raise ProviderError("INVALID_SEARCH_RESPONSE")
            for row in data["results"]:
                if not isinstance(row, dict):
                    batch.rejected += 1
                    continue
                try:
                    item = recent_linkedin_listing(row, str(row.get("content") or ""), now)
                except (ValueError, ValidationError):
                    item = None
                if item is None:
                    batch.rejected += 1
                elif all(existing.external_id != item.external_id for existing in batch.items):
                    batch.items.append(item)
                if len(batch.items) >= query.max_items:
                    batch.warnings.append("ITEM_LIMIT_REACHED")
                    return batch
        return batch
