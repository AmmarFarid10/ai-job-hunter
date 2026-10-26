from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    app_domain: str | None = None
    min_storage_free_mb: int = Field(default=100, ge=1, le=100000)
    environment: Literal["development", "test", "production"] = "development"
    require_email_verification: bool = False
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_tls: Literal["starttls", "ssl"] = "starttls"
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    auth_sender_email: str | None = Field(default=None, pattern=r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
    daily_auth_mail_limit: int = Field(default=500, ge=1, le=100000)
    global_daily_discovery_limit: int = Field(default=100, ge=1, le=100000)
    global_monthly_discovery_limit: int = Field(default=1000, ge=1, le=1000000)
    daily_discovery_limit: int = Field(default=20, ge=1, le=10000)
    daily_generation_limit: int = Field(default=30, ge=1, le=10000)
    daily_upload_limit: int = Field(default=20, ge=1, le=10000)
    daily_matching_limit: int = Field(default=100, ge=1, le=10000)
    daily_report_limit: int = Field(default=10, ge=1, le=10000)
    max_candidates_per_user: int = Field(default=10, ge=1, le=1000)
    gateway_token: SecretStr | None = None
    allow_api_key_auth: bool = True
    allow_admin_bootstrap: bool = True
    api_key: SecretStr = Field(min_length=32)
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://jobhunter:localdev@localhost:5432/jobhunter"
    )
    storage_dir: Path = Path("storage")
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    match_threshold: int = Field(default=80, ge=0, le=100)
    discovery_config_file: Path = Path("discovery_sources.json")
    brave_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_extraction_model: str | None = None
    matching_timeout_seconds: int = Field(default=90, ge=5, le=180)
    gmail_token_file: Path | None = None
    gmail_alert_query: str = (
        "from:(jobalerts-noreply@linkedin.com OR jobs-noreply@linkedin.com) newer_than:14d"
    )
    discovery_timeout_seconds: int = Field(default=90, ge=5, le=180)

    admin_email: str | None = Field(default=None, pattern=r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
    admin_password: SecretStr | None = Field(default=None, min_length=12, max_length=128)
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str = "http://localhost:3000/api/oauth/google/callback"

    notification_mode: Literal["mock", "live"] = "mock"
    scheduler_enabled: bool = True
    dashboard_url: str = "http://localhost:3000"
    gmail_sender_email: str | None = Field(
        default=None, pattern=r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$"
    )
    gmail_send_token_file: Path | None = None
    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = Field(default=None, pattern=r"^[0-9]+$")
    whatsapp_graph_version: str | None = Field(default=None, pattern=r"^v[0-9]+\.[0-9]+$")
    whatsapp_template_name: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")
    whatsapp_template_language: str = "en_US"

    @model_validator(mode="after")
    def production_requirements(self) -> "Settings":
        if self.environment != "production":
            return self
        if not self.require_email_verification or not self.smtp_host or not self.auth_sender_email:
            raise ValueError(
                "Production requires email verification and configured "
                "authentication email delivery"
            )
        if self.allow_api_key_auth or self.allow_admin_bootstrap:
            raise ValueError(
                "Production must disable maintenance-key authentication "
                "and web administrator bootstrap"
            )
        if not self.gateway_token or len(self.gateway_token.get_secret_value()) < 32:
            raise ValueError(
                "Production requires a private gateway token of at least 32 characters"
            )
        public = urlsplit(self.dashboard_url)
        if (
            public.scheme != "https"
            or not public.hostname
            or public.hostname in {"localhost", "127.0.0.1"}
            or public.username
            or public.query
            or public.fragment
            or public.path not in {"", "/"}
        ):
            raise ValueError("Production requires a public HTTPS dashboard origin")
        if self.app_domain and self.dashboard_url.rstrip("/") != "https://" + self.app_domain:
            raise ValueError("Dashboard URL must match APP_DOMAIN")
        db = self.database_url.get_secret_value()
        if "localdev" in db or "test:test" in db or "localhost" in db:
            raise ValueError("Production requires a dedicated database with private credentials")
        if "replace" in self.api_key.get_secret_value().lower():
            raise ValueError("Production secrets must be generated, not example values")
        if self.google_client_id:
            callback = self.dashboard_url.rstrip("/") + "/api/oauth/google/callback"
            if self.google_redirect_uri != callback or not self.google_client_secret:
                raise ValueError("Google callback must use the production dashboard origin")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # Loaded from environment by BaseSettings.
