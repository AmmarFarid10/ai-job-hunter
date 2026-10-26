import json
import logging
import secrets
import tempfile
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.responses import Response

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.discovery import router as discovery_router
from app.api.limits import RequestSizeLimit
from app.api.matching import router as matching_router
from app.api.review import router as review_router
from app.api.routes import router
from app.api.tailoring import router as tailoring_router
from app.config import get_settings
from app.database import get_engine
from app.integrations.discovery.base import ProviderError
from app.services.scheduler import make_scheduler

logger = logging.getLogger("jobhunter")
logging.basicConfig(level=logging.INFO, format="%(message)s")
# Avoid logging SQL statements or exception parameters (may contain personal data).
logging.getLogger("sqlalchemy.engine").setLevel(logging.CRITICAL)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()  # Fail startup on missing/invalid configuration.
    if settings.environment == "production":
        from app.integrations.discovery.registry import build_registry

        registry = build_registry(settings)
        if not any(
            item["kind"] in {"greenhouse", "lever", "career_page", "tavily", "brave"}
            and item["configured"]
            for item in registry.descriptions
        ):
            raise RuntimeError(
                "Configure at least one public discovery source before production startup"
            )
    scheduler = make_scheduler() if get_settings().scheduler_enabled else None
    if scheduler is not None:
        scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await get_engine().dispose()


app = FastAPI(title="AI Job Hunter", version="0.5.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(router)
app.include_router(discovery_router)
app.include_router(matching_router)
app.include_router(tailoring_router)
app.include_router(review_router)
app.include_router(dashboard_router)
app.add_middleware(RequestSizeLimit)


@app.middleware("http")
async def request_log(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = uuid.uuid4().hex
    start = time.monotonic()
    settings = get_settings()
    response: Response
    gateway = request.headers.get("X-Gateway-Token", "")
    if (
        settings.environment == "production"
        and request.url.path.startswith("/api/v1")
        and (
            not settings.gateway_token
            or not secrets.compare_digest(
                gateway.encode(), settings.gateway_token.get_secret_value().encode()
            )
        )
    ):
        response = JSONResponse({"detail": "Gateway access required"}, status_code=403)
    else:
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                json.dumps(
                    {
                        "event": "request_failed",
                        "request_id": request_id,
                        "exception_type": type(exc).__name__,
                    }
                )
            )
            # No exception text, SQL parameters, request bodies or tokens in logs/responses.
            response = JSONResponse({"detail": "Internal server error"}, status_code=500)

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    # Do not log paths (IDs), query strings, payloads, credentials or exception values.
    logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "method": request.method,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - start) * 1000),
            }
        )
    )
    return response


@app.exception_handler(IntegrityError)
async def integrity_error(_: Request, __: IntegrityError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "Record conflicts with stored data"})


@app.exception_handler(SQLAlchemyError)
async def database_error(_: Request, __: SQLAlchemyError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def readiness() -> JSONResponse:
    try:
        async with get_engine().connect() as connection:
            from alembic.config import Config
            from alembic.script import ScriptDirectory

            expected = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
            actual = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            if actual != expected:
                raise RuntimeError("Database migration required")
        storage = get_settings().storage_dir
        storage.mkdir(parents=True, exist_ok=True, mode=0o700)
        import shutil

        if shutil.disk_usage(storage).free < get_settings().min_storage_free_mb * 1024 * 1024:
            raise RuntimeError("Storage capacity low")
        with tempfile.TemporaryFile(dir=storage) as probe:
            probe.write(b"ready")
        return JSONResponse({"status": "ready"})
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready"})


@app.exception_handler(ProviderError)
async def provider_error(_: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": exc.code})


@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
                for error in exc.errors()
            ]
        },
    )
