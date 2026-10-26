import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database import get_session
from app.main import app
from app.models import Base

os.environ.setdefault("API_KEY", "test-api-key-at-least-thirty-two-characters")


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    # Safety guard: integration fixtures deliberately truncate tables.
    if not url.rsplit("/", 1)[-1].endswith("_test"):
        pytest.fail("TEST_DATABASE_URL database name must end in _test")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
        await connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    factory = async_sessionmaker(engine, expire_on_commit=False, info={"system": True})

    async def override_session() -> AsyncIterator[object]:
        async with factory() as session, session.begin():
            yield session

    os.environ["STORAGE_DIR"] = str(tmp_path)
    get_settings.cache_clear()
    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": os.environ["API_KEY"]},
    ) as http:
        yield http
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    await engine.dispose()
