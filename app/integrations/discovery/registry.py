import json
from typing import Any
from urllib.parse import urlsplit

from pydantic import TypeAdapter, ValidationError

from app.config import Settings, get_settings
from app.domain.discovery import SourceConfig
from app.integrations.discovery.base import DiscoveryProvider, ProviderError
from app.integrations.discovery.career import CareerPageProvider
from app.integrations.discovery.email import GmailAlertProvider
from app.integrations.discovery.feeds import GreenhouseProvider, LeverProvider
from app.integrations.discovery.http import SafeHTTP
from app.integrations.discovery.mock import MockProvider
from app.integrations.discovery.search import BraveSearchProvider, TavilySearchProvider


class ProviderRegistry:
    def __init__(
        self,
        providers: dict[str, DiscoveryProvider],
        descriptions: list[dict[str, Any]] | None = None,
    ) -> None:
        self.providers = providers
        self.descriptions = descriptions or [
            {"name": name, "kind": "custom", "configured": True} for name in providers
        ]

    def select(self, names: list[str]) -> dict[str, DiscoveryProvider]:
        configured = {item["name"] for item in self.descriptions if item.get("configured")}
        if any(name not in self.providers or name not in configured for name in names):
            raise ProviderError("UNKNOWN_OR_DISABLED_SOURCE")
        return {name: self.providers[name] for name in names}


def load_sources(settings: Settings) -> list[SourceConfig]:
    if not settings.discovery_config_file.exists():
        return [SourceConfig(name="mock", kind="mock")]
    try:
        if settings.discovery_config_file.stat().st_size > 100000:
            raise ValueError("configuration too large")
        sources = TypeAdapter(list[SourceConfig]).validate_python(
            json.loads(settings.discovery_config_file.read_text())
        )
        if len(sources) > 30 or len({source.name for source in sources}) != len(sources):
            raise ValueError("invalid source count or duplicate names")
        return sources
    except (OSError, ValueError, ValidationError) as exc:
        raise ProviderError("INVALID_DISCOVERY_CONFIGURATION") from exc


def build_registry(settings: Settings) -> ProviderRegistry:
    providers: dict[str, DiscoveryProvider] = {}
    descriptions: list[dict[str, Any]] = []
    for source in load_sources(settings):
        if not source.enabled or (settings.environment == "production" and source.kind == "mock"):
            continue
        provider: DiscoveryProvider
        configured = True
        match source.kind:
            case "mock":
                provider = MockProvider()
            case "greenhouse":
                provider = GreenhouseProvider(source, SafeHTTP({"boards-api.greenhouse.io"}))
            case "lever":
                provider = LeverProvider(source, SafeHTTP({"api.lever.co", "api.eu.lever.co"}))
            case "career_page":
                provider = CareerPageProvider(
                    source, SafeHTTP({urlsplit(source.url or "").hostname or ""})
                )
            case "brave":
                provider = BraveSearchProvider(
                    SafeHTTP({"api.search.brave.com"}), settings.brave_api_key
                )
                configured = bool(settings.brave_api_key)
            case "tavily":
                provider = TavilySearchProvider(
                    SafeHTTP({"api.tavily.com"}), settings.tavily_api_key
                )
                configured = bool(settings.tavily_api_key)
            case "gmail":
                provider = GmailAlertProvider(
                    SafeHTTP({"oauth2.googleapis.com", "gmail.googleapis.com"}),
                    settings.gmail_token_file,
                    settings.gmail_alert_query,
                )
                configured = settings.gmail_token_file is not None
        providers[source.name] = provider
        descriptions.append({"name": source.name, "kind": source.kind, "configured": configured})
    return ProviderRegistry(providers, descriptions)


def get_registry() -> ProviderRegistry:
    return build_registry(get_settings())
