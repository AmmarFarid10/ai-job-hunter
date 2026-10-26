from typing import Protocol

from app.domain.discovery import DiscoveryQuery, ProviderBatch


class ProviderError(Exception):
    """Safe machine-readable error; never include remote content or credentials."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DiscoveryProvider(Protocol):
    async def collect(self, query: DiscoveryQuery) -> ProviderBatch: ...
