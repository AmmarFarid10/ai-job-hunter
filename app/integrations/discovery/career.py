import hashlib
import json
from typing import Any

from app.domain.discovery import DiscoveryQuery, ProviderBatch, SourceConfig
from app.domain.posting_dates import parse_date
from app.integrations.discovery.base import ProviderError
from app.integrations.discovery.feeds import add_listing
from app.integrations.discovery.http import SafeHTTP
from app.integrations.discovery.parsing import job_postings, plain_text


class CareerPageProvider:
    """Read only explicitly permitted, configured pages with JobPosting JSON-LD."""

    def __init__(self, config: SourceConfig, http: SafeHTTP) -> None:
        self.config, self.http = config, http

    async def collect(self, query: DiscoveryQuery) -> ProviderBatch:
        assert self.config.url is not None
        # Respect robots rules for this agent as a second restriction; permission is also required.
        from urllib.parse import urlsplit
        from urllib.robotparser import RobotFileParser

        parts = urlsplit(self.config.url)
        robots_url = f"https://{parts.netloc}/robots.txt"
        try:
            robots = await self.http.request("GET", robots_url)
        except ProviderError as exc:
            if exc.code != "HTTP_404":
                raise
        else:
            parser = RobotFileParser()
            parser.parse(robots.decode("utf-8", errors="replace").splitlines())
            if not parser.can_fetch("AIJobHunter", self.config.url):
                raise ProviderError("ROBOTS_DISALLOWED")
            delay = parser.crawl_delay("AIJobHunter") or parser.crawl_delay("*") or 0
            if float(delay) > 0:
                # Do not silently violate long crawl delays within a synchronous run.
                raise ProviderError("CRAWL_DELAY_REQUIRES_MANUAL_IMPORT")
        page = await self.http.request(
            "GET", self.config.url, headers={"User-Agent": "AIJobHunter/0.2"}
        )
        batch = ProviderBatch()
        postings = job_postings(page.decode("utf-8", errors="replace"))
        if not postings:
            batch.warnings.append("NO_STRUCTURED_JOB_POSTINGS")
        for row in postings:
            organization = row.get("hiringOrganization")
            company = organization.get("name") if isinstance(organization, dict) else None
            identifier = row.get("identifier")
            if isinstance(identifier, dict):
                identifier = identifier.get("value")
            url = row.get("url") or self.config.url
            external = (
                str(identifier)
                if identifier is not None
                else hashlib.sha256((str(url) + "|" + str(row.get("title"))).encode()).hexdigest()
            )
            locations: list[str] = []
            raw_locations: Any = row.get("jobLocation", [])
            if isinstance(raw_locations, dict):
                raw_locations = [raw_locations]
            if isinstance(raw_locations, list):
                for location in raw_locations:
                    address = location.get("address") if isinstance(location, dict) else None
                    if isinstance(address, dict):
                        locations.append(
                            ", ".join(
                                str(address[key])
                                for key in ["addressLocality", "addressRegion", "addressCountry"]
                                if address.get(key)
                            )
                        )
            if row.get("jobLocationType") == "TELECOMMUTE":
                locations.insert(0, "Remote (eligibility unconfirmed)")
            restrictions = row.get("applicantLocationRequirements")
            add_listing(
                batch,
                query,
                {
                    "external_id": external,
                    "posted_at": parse_date(row.get("datePosted")),
                    "posting_date_evidence": "JobPosting.datePosted"
                    if row.get("datePosted")
                    else None,
                    "title": row.get("title"),
                    "company": company,
                    "employer_job_id": str(identifier) if identifier is not None else None,
                    "description": plain_text(str(row.get("description") or "")),
                    "source_url": url,
                    "application_url": url,
                    "application_instructions": plain_text(
                        str(row.get("applicationInstructions") or "")
                    )
                    or None,
                    "location": "; ".join(locations)[:300] or None,
                    "geographic_restrictions": json.dumps(restrictions)[:3000]
                    if restrictions
                    else None,
                    "compensation": json.dumps(row["baseSalary"])[:500]
                    if row.get("baseSalary")
                    else None,
                    "requires_review": not bool(company),
                },
            )
        return batch
