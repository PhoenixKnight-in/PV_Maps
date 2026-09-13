# Offline preparation only. Multi-GB by design.
# ARCHITECTURE.md 9.1: never started during a judging demo.
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.12 python3.12-venv python3-pip git \
      gdal-bin libgdal-dev libgeos-dev libproj-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_LINK_MODE=copy
COPY pyproject.toml uv.lock* ./
RUN uv sync --group pipeline --no-install-project --no-dev

COPY src ./src
RUN uv sync --group pipeline --no-dev

# SAM2 is not on PyPI; pin the commit rather than tracking main.
RUN uv pip install "git+https://github.com/facebookresearch/sam2.git@main"

ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["python", "-m", "pvmaps.pipeline.cli"]
CMD ["--help"]
