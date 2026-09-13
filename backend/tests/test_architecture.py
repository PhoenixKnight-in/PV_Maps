"""Invariants that are cheap to state and expensive to rediscover.

ARCHITECTURE.md 1:

    "The request path must not load SAM2, run a GPU model, or create a new roof
     mask."

ARCHITECTURE.md 11:

    "Phase 2 introduces a utility-integration adapter behind the API."
    (Phase 1 reaches none of it.)

Both are the kind of rule that holds for months and then quietly stops holding,
because an import is one line and nobody reads the import block in review. So
they are tests.

The imports under test are done in a subprocess with a clean interpreter.
Checking `sys.modules` in-process would be meaningless here: pytest has already
collected every other test module, and those legitimately import things the API
must not.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

OFFLINE_ONLY = [
    "torch",
    "torchvision",
    "sam2",
    "pvlib",
    "rasterio",
    "geopandas",
    "shapely",
    "pandas",
]
"""The offline plane's dependencies. `docker/api.Dockerfile` installs the `api`
group only, so importing any of these from a request handler would not be a
slow request — it would be an ImportError in production and a green test suite
on a developer laptop that happens to have them."""

PHASE_2_ONLY = ["ortools", "pvmaps.phase2"]
"""ARCHITECTURE.md 11. The DT-quota allocator is built and tested and reachable
from no Phase 1 route. `ortools` is ~100 MB and is absent from the API image."""


def _modules_loaded_by(target: str) -> set[str]:
    """Import `target` in a fresh interpreter; report what came with it."""
    script = textwrap.dedent(
        f"""
        import json, sys
        sys.path.insert(0, {str(SRC)!r})
        import {target}
        print(json.dumps(sorted(sys.modules)))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, f"importing {target} failed:\n{proc.stderr}"
    return set(json.loads(proc.stdout.splitlines()[-1]))


def _assert_absent(loaded: set[str], forbidden: list[str], target: str) -> None:
    hits = sorted(
        name
        for name in loaded
        if any(name == f or name.startswith(f"{f}.") for f in forbidden)
    )
    assert not hits, (
        f"importing {target} pulled in {hits}.\n"
        f"ARCHITECTURE.md 1: the request path does no physics and the API image "
        f"does not ship these. Move the import into the offline pipeline, or make "
        f"it lazy inside the function that needs it."
    )


def test_the_api_does_not_load_the_offline_plane() -> None:
    loaded = _modules_loaded_by("pvmaps.api.main")
    _assert_absent(loaded, OFFLINE_ONLY, "pvmaps.api.main")


def test_the_api_does_not_load_phase_2() -> None:
    loaded = _modules_loaded_by("pvmaps.api.main")
    _assert_absent(loaded, PHASE_2_ONLY, "pvmaps.api.main")


def test_the_calculation_engine_needs_no_web_or_database_stack() -> None:
    """pyproject.toml: the core must "stay installable on a laptop with no
    database, no GPU and no network -- that is what makes build-order items 1
    and 2 possible before any infrastructure runs."

    So `pvmaps.sizing` and `pvmaps.tariff` may not drag in FastAPI or SQLAlchemy
    either. This is the test that keeps the pure modules genuinely pure.
    """
    loaded = _modules_loaded_by("pvmaps.sizing")
    _assert_absent(
        loaded,
        ["fastapi", "starlette", "sqlalchemy", "asyncpg", "geoalchemy2", "uvicorn"],
        "pvmaps.sizing",
    )
    _assert_absent(loaded, OFFLINE_ONLY, "pvmaps.sizing")


def test_the_pipeline_does_not_need_the_api_stack() -> None:
    """The reverse of the rule above, and the one that actually bit.

    `docker/pipeline.Dockerfile` installs the `pipeline` group, which has no
    fastapi, no sqlalchemy and no geoalchemy2. `pipeline.roofs` once imported the
    two SRID constants from `db.models` -- two integers, dragging the whole ORM
    layer with them -- and the pipeline image would have failed on import. They
    live in `pvmaps.crs` now, which depends on nothing.
    """
    for module in ("pvmaps.pipeline.roofs", "pvmaps.pipeline.iou", "pvmaps.crs"):
        loaded = _modules_loaded_by(module)
        _assert_absent(
            loaded,
            ["fastapi", "starlette", "sqlalchemy", "geoalchemy2", "asyncpg", "uvicorn"],
            module,
        )


def test_the_seeder_needs_neither_the_web_stack_nor_the_physics_stack() -> None:
    """`docker/seed.Dockerfile` installs the `seed` group -- psycopg and typer.

    That image exists so the person recreating the demo database at 2am does not
    have to build a multi-GB CUDA image to write fifteen rows. It only stays small
    while the seeder imports nothing heavier: one `from shapely...` at module
    level in `seed.py` would move the pilot data behind a GPU image again, and the
    symptom would be an ImportError in the one container that has to work.
    """
    loaded = _modules_loaded_by("pvmaps.pipeline.seed")
    _assert_absent(loaded, OFFLINE_ONLY, "pvmaps.pipeline.seed")
    _assert_absent(
        loaded,
        ["fastapi", "starlette", "sqlalchemy", "asyncpg", "geoalchemy2", "uvicorn"],
        "pvmaps.pipeline.seed",
    )


def test_the_wire_schemas_need_only_pydantic() -> None:
    """`scripts/build_demo_fallback.py` serialises through `api.schemas` so the
    bundled demo fixture cannot drift from the live response. That only works
    while importing the schemas does not drag in the web stack."""
    loaded = _modules_loaded_by("pvmaps.api.schemas")
    _assert_absent(
        loaded, ["fastapi", "starlette", "sqlalchemy", "asyncpg", "uvicorn"], "pvmaps.api.schemas"
    )
