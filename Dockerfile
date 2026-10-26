FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock ./
COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /uvx /usr/local/bin/
RUN uv sync --frozen --no-dev
COPY . .
RUN useradd --create-home app && mkdir -p /app/storage && chown -R app:app /app
EXPOSE 8000
CMD ["sh", "-c", ".venv/bin/alembic upgrade head && exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log"]

FROM base AS test
RUN uv sync --frozen --extra dev
USER app

FROM base AS runtime
USER app
