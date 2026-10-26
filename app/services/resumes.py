import hashlib
import os
import shutil
import uuid

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.integrations.pdf import extract_pdf
from app.models import Candidate, ResumeDraft
from app.repositories.common import require


async def ingest_resume(
    session: AsyncSession, candidate_id: uuid.UUID, file: UploadFile, settings: Settings
) -> ResumeDraft:
    await require(session, Candidate, candidate_id)
    from app.services.quotas import reserve_usage

    await reserve_usage(session, "upload")
    content = await file.read(settings.max_upload_bytes + 1)
    await file.close()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, "PDF exceeds upload size limit")
    try:
        text, suggestions, warnings = await run_in_threadpool(extract_pdf, content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    storage = settings.storage_dir.resolve()
    storage.mkdir(mode=0o700, parents=True, exist_ok=True)
    if shutil.disk_usage(storage).free < len(content) + settings.min_storage_free_mb * 1024 * 1024:
        raise HTTPException(507, "Storage capacity low. Contact the administrator")
    key = f"{uuid.uuid4().hex}.pdf"
    path = storage / key
    # Exclusive creation and restrictive mode; never use the uploaded filename.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        draft = ResumeDraft(
            candidate_id=candidate_id,
            storage_key=key,
            sha256=hashlib.sha256(content).hexdigest(),
            extracted_text=text,
            suggestions=suggestions,
            warnings=warnings,
        )
        session.add(draft)
        await session.flush()
        # Commit inside this operation so file cleanup also covers commit failures.
        await session.commit()
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return draft
