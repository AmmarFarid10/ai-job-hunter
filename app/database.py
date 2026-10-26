from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app import ownership  # noqa: F401 -- install fail-closed SQLAlchemy listeners
from app.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(
        get_settings().database_url.get_secret_value(),
        pool_pre_ping=True,
        connect_args={"timeout": 5, "command_timeout": 30},
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            yield session
