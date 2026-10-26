from app.domain.discovery import DiscoveryQuery, Listing, ProviderBatch


class MockProvider:
    async def collect(self, query: DiscoveryQuery) -> ProviderBatch:
        items = [
            Listing(
                external_id="phase2-demo-python",
                title="Senior Python Backend Engineer (DEMO)",
                company="Fictional Discovery Demo Employer",
                description="Fictional fixture for development. Build Python/FastAPI APIs. "
                "No real vacancy or eligibility claim. Do not apply.",
                source_url="https://example.invalid/jobs/phase2-demo-python",
                application_url="https://example.invalid/jobs/phase2-demo-python",
                employer_job_id="phase2-demo-python",
                location="Remote — eligibility unknown",
            ),
            Listing(
                external_id="phase2-demo-post",
                title="Python engineering hiring post (DEMO)",
                company=None,
                description="Fictional incomplete hiring post; review required.",
                source_url="https://example.invalid/posts/phase2-demo-post",
                requires_review=True,
            ),
        ]
        return ProviderBatch(
            items=[item for item in items if query.relevant(item.title)][: query.max_items]
        )
