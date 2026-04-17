FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/root/.cache/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

FROM base AS dependencies

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM dependencies AS development

RUN uv sync --frozen
COPY . .
CMD ["uv", "run", "python", "-m", "docai"]

FROM dependencies AS production

COPY src/ ./src/
COPY --from=dependencies /app/.venv ./.venv

RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD [".venv/bin/python", "-m", "docai", "--host", "0.0.0.0", "--port", "8080"]
