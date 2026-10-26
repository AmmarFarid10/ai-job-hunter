"""Validate deployment configuration without printing secrets or opening network connections."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings  # noqa: E402


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env.production")
    if not path.is_file():
        print("FAIL: production environment file not found")
        return 1
    if os.name != "nt" and path.stat().st_mode & 0o077:
        print("FAIL: production environment file must have owner-only permissions (chmod 600)")
        return 1
    try:
        from dotenv import dotenv_values

        values = dotenv_values(path)
        password = values.get("POSTGRES_PASSWORD")
        if not password:
            raise ValueError()
        settings = Settings(
            _env_file=path, database_url=f"postgresql+asyncpg://app:{password}@db:5432/jobhunter"
        )
        if settings.environment != "production":
            raise ValueError()
        text = path.read_text()
        if (
            "replace-with-" in text
            or "jobs.example.com" in settings.dashboard_url
            or not settings.smtp_host
            or settings.smtp_host.endswith(".example.com")
        ):
            raise ValueError()
    except Exception:
        print("FAIL: production configuration is incomplete or unsafe; see .env.production.example")
        return 1
    print(
        "PASS: production configuration validated. "
        "Live DNS/TLS and email delivery still need a smoke check."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
