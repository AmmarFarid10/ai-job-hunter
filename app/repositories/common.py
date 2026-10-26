import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Base


async def require[T: Base](
    session: AsyncSession, model: type[T], record_id: uuid.UUID, *, lock: bool = False
) -> T:
    query = select(model).where(model.id == record_id)  # type: ignore[attr-defined]
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    record = await session.scalar(query)
    if record is None:
        raise HTTPException(404, f"{model.__name__} not found")
    return record
