# Offline preparation only. ARCHITECTURE.md 9.1: never started during a demo.
#
# THE BASE IS `base`, NOT `cudnn-runtime`, and that is deliberate.
#
# PyTorch's Linux wheels vendor their own CUDA and cuDNN -- see the
# `nvidia-cuda-runtime`, `nvidia-cudnn` and `cuda-toolkit` entries torch pulls in
# `uv.lock`. A `cudnn-runtime` base therefore ships a second copy of libraries
# torch will not load, for about 1.5 GB and a 670 MB layer that is its own
# reliability problem on a domestic connection. The NVIDIA container runtime
# injects the driver either way, which is the part that cannot come from pip.
#
# PYTHON COMES FROM uv, NOT FROM apt. Ubuntu 22.04 (jammy) ships python3.10 and
# has no python3.12 package at all, so the `apt-get install python3.12` this file
# used to carry could never have succeeded -- the image had never been built.
# uv downloads a managed CPython matching `requires-python`, which is one fewer
# thing to keep in step with the base image.
FROM nvidia/cuda:12.4.1-base-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1

# git is for the SAM2 install below. No GDAL/GEOS/PROJ development packages:
# the rasterio, shapely and pyproj wheels vendor those libraries, and installing
# the system ones only adds weight and a second version to disagree with.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app
# UV_HTTP_TIMEOUT: the default is 30s and torch is a multi-gigabyte wheel.
# On anything short of a datacentre link the default guarantees a failed
# build, and the error it produces blames the network rather than the timeout.
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=automatic UV_PYTHON=3.12
ENV UV_HTTP_TIMEOUT=600 UV_CONCURRENT_DOWNLOADS=4

COPY pyproject.toml uv.lock* ./
RUN uv sync --group pipeline --no-install-project --no-dev

COPY src ./src
RUN uv sync --group pipeline --no-dev

# SAM2 is not on PyPI.
#
# `--no-deps` because its metadata re-pins torch, which would undo the resolved
# environment above and re-download several gigabytes. But --no-deps is not free:
# it also skips the dependencies SAM2 genuinely imports at runtime, and the
# failure lands at `build_sam2` rather than at build time. hydra-core is what
# resolves `configs/sam2.1/...` and iopath is what opens the checkpoint, so both
# are installed explicitly here. Keep this list in step with SAM2's setup.py.
RUN uv pip install --no-deps "git+https://github.com/facebookresearch/sam2.git@main" \
 && uv pip install "hydra-core>=1.3" "iopath>=0.1.10" "tqdm>=4.66"

# The segmenter service (pvmaps.segmenter) runs from THIS image, so it needs a
# web server. Installed here, in a late layer, rather than in pyproject's
# `pipeline` group on purpose: touching pyproject.toml invalidates the layer
# that downloads torch and the CUDA wheels, which is ~1.7 GB and the better part
# of an hour on a normal connection. A dependency that is only needed at the end
# belongs at the end.
RUN uv pip install "fastapi>=0.115" "uvicorn[standard]>=0.32"

# PATH before the check below, not after the ENTRYPOINT: this base image carries
# no system python at all (uv's managed interpreter lives in the venv), so a bare
# `python` here exits 127 -- "not found" -- which reads like a broken image rather
# than a missing PATH.
ENV PATH="/app/.venv/bin:$PATH"

# Fail the BUILD, not the first run, if that dependency list is wrong.
RUN python -c "import sam2, hydra, iopath; from sam2.build_sam import build_sam2; \
from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator; print('sam2 imports OK')"

# Weights are NOT baked in. They are ~180 MB, they change independently of the
# code, and .gitignore excludes *.pt. docker-compose mounts ./checkpoints here
# and `pipeline fetch-checkpoint` fills it.
VOLUME ["/checkpoints", "/data"]

ENTRYPOINT ["python", "-m", "pvmaps.pipeline.cli"]
CMD ["--help"]
