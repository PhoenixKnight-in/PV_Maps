# Database preparation: `pvmaps.pipeline.cli seed`, and nothing heavier.
#
# The seeder writes with the SYNCHRONOUS driver because it is a batch write in
# the offline plane (ARCHITECTURE.md 1), so it cannot run from the api image --
# that one carries asyncpg only. It also must not require the pipeline image:
# that is CUDA, torch and multi-GB, ARCHITECTURE.md 9.1 says it is never started
# during a demo, and the person recreating the demo database the night before
# should not have to build it to write fifteen rows.
#
# Hence a third, small image, holding the `seed` group: psycopg and typer.
# `yield` and `iou` are NOT available here -- they need pvlib and shapely and
# belong in docker/pipeline.Dockerfile. Every command in the CLI imports lazily,
# so asking this image for one of those fails with a sentence rather than at
# startup.
FROM ghcr.io/astral-sh/uv:0.5-python3.12-bookworm-slim AS build

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock* ./
RUN uv sync --group seed --no-install-project --no-dev

COPY src ./src
RUN uv sync --group seed --no-dev


FROM python:3.12-slim-bookworm AS runtime

RUN useradd --create-home --uid 10001 pvmaps
WORKDIR /app

COPY --from=build --chown=pvmaps:pvmaps /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

USER pvmaps
ENTRYPOINT ["python", "-m", "pvmaps.pipeline.cli"]
CMD ["--help"]
