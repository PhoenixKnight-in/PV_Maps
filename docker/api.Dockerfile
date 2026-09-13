# Web request path. Deliberately carries no torch, pvlib, rasterio, geopandas
# or OR-Tools -- ARCHITECTURE.md 1: nothing that can reach a request handler
# may depend on the offline plane.
FROM ghcr.io/astral-sh/uv:0.5-python3.12-bookworm-slim AS build

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependency layer first so source edits do not re-resolve the tree.
COPY pyproject.toml uv.lock* ./
RUN uv sync --group api --no-install-project --no-dev

COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN uv sync --group api --no-dev


FROM python:3.12-slim-bookworm AS runtime

RUN useradd --create-home --uid 10001 pvmaps
WORKDIR /app

COPY --from=build --chown=pvmaps:pvmaps /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

USER pvmaps
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/healthz')"

# --no-access-log: uvicorn's access log prints the full request line, which for
# GET /v1/search?q=<someone's address> puts a household's address into container
# logs (ARCHITECTURE.md 8). pvmaps.api.logging disables that logger in code as
# well; this is the same rule stated where an operator will see it.
CMD ["uvicorn", "pvmaps.api.main:app",      "--host", "0.0.0.0", "--port", "8000",      "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
