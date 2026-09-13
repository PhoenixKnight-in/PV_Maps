"""What ends up inside the wheel — NFR-4.

    "Nothing regulatory is hardcoded. Everything lives in versioned JSON."

That only holds if the JSON is deployed with the code that reads it. The rule
packs live inside the package directory precisely so that `packages` ships them,
and this file is what keeps that arrangement true.

It is also here because of a bug that hid perfectly. `pyproject.toml` carried a
`force-include` of `src/pvmaps/config`, which added every rule pack to the wheel a
second time at a path it already occupied. Hatchling refuses that outright:

    ValueError: A second file is being added to the wheel archive at the same
    path: `pvmaps/config/__init__.py`.

An editable install never builds a wheel archive, so `uv sync`, the whole test
suite and every local run were green while `uv build` — and any non-editable
install of this package — could not complete at all.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
WHEEL = PYPROJECT["tool"]["hatch"]["build"]["targets"]["wheel"]

CONFIG_DIRS = ("tariffs", "subsidies", "solar_assumptions")


def test_the_rule_packs_sit_inside_the_shipped_package() -> None:
    """NFR-4. A rule pack outside `packages` is a rule pack that exists on the
    developer's laptop and nowhere else."""
    package_roots = [BACKEND / p for p in WHEEL["packages"]]
    for name in CONFIG_DIRS:
        directory = BACKEND / "src" / "pvmaps" / "config" / name
        assert directory.is_dir(), f"{name} rule-pack directory is missing"
        assert list(directory.glob("*.json")), f"{name} holds no versioned rule pack"
        assert any(directory.is_relative_to(root) for root in package_roots), (
            f"{directory} is outside {WHEEL['packages']}, so it would not be installed"
        )


def test_nothing_is_force_included_over_the_package_tree() -> None:
    """The exact shape of the bug above: a forced include of a path `packages`
    already covers makes the wheel unbuildable, and only the wheel — every
    editable install stays green."""
    forced = WHEEL.get("force-include", {})
    package_roots = [(BACKEND / p).resolve() for p in WHEEL["packages"]]
    for source in forced:
        resolved = (BACKEND / source).resolve()
        assert not any(resolved.is_relative_to(root) for root in package_roots), (
            f"force-include of {source!r} duplicates files that `packages` already "
            f"ships; hatchling refuses to build the wheel when two entries land at "
            f"the same archive path"
        )


def test_the_request_path_ships_without_the_offline_plane() -> None:
    """ARCHITECTURE.md 1, stated as a dependency fact rather than an import one.

    `test_architecture.py` proves the API does not IMPORT torch or pvlib. This
    proves the api image is not asked to INSTALL them — the two fail differently
    and only this one shows up as a multi-gigabyte container.
    """
    groups = PYPROJECT["dependency-groups"]
    api_deps = " ".join(groups["api"]).lower()
    for forbidden in ("torch", "pvlib", "rasterio", "geopandas", "shapely", "ortools"):
        assert forbidden not in api_deps, f"the api group installs {forbidden}"


def test_the_seed_image_stays_small() -> None:
    """docker/seed.Dockerfile exists so that writing fifteen rows does not require
    building a CUDA image. That holds only while the `seed` group stays this
    short."""
    groups = PYPROJECT["dependency-groups"]
    seed_deps = " ".join(groups["seed"]).lower()
    assert "psycopg" in seed_deps, "the seeder writes with the synchronous driver"
    for forbidden in ("torch", "pvlib", "rasterio", "geopandas", "fastapi", "sqlalchemy"):
        assert forbidden not in seed_deps, f"the seed group installs {forbidden}"
