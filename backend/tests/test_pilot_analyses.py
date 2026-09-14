"""The committed pvlib output for the pilot roofs — FR-2, PRD 10.

    "Yield model | Within a defensible published Tamil Nadu range"

`src/pvmaps/pipeline/analyses/pilot_roof_analyses.json` is what makes that
criterion checkable without a GPU image and without a database: it is the
`roof_analyses` rows `pipeline yield --pilot` produced, committed so that the
seeder can write them and the offline bundle can read them.

Two ways this file can go wrong, and both are silent:

* It stops covering a pilot roof. That roof quietly reverts to the regional band
  and the screen still renders, just less honestly.
* Its numbers drift outside the published band. PRD 10 is explicit that this is
  evidence the physics is wrong, not a reason to widen the band — so the check
  belongs here rather than in a comment.

Regenerate with:

    pipeline yield --pilot --dry-run --out src/pvmaps/pipeline/analyses/pilot_roof_analyses.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pvmaps.api.repository import YieldRow
from pvmaps.pipeline.seed import (
    PILOT_ANALYSES_PATH,
    PILOT_ROOFS,
    load_pilot_analyses,
    seed_pilot,
)
from pvmaps.sizing.assumptions import load_assumptions

ROWS = load_pilot_analyses()


def test_the_analyses_ship_inside_the_package() -> None:
    """Same failure `test_packaging.py` guards the rule packs against: a data file
    outside `packages` is a data file that exists on the developer's laptop and
    nowhere else. `docker/seed.Dockerfile` installs the package and nothing more,
    so a file it does not carry is a database that quietly seeds no analyses."""
    import tomllib

    backend = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((backend / "pyproject.toml").read_text(encoding="utf-8"))
    roots = [
        (backend / p).resolve()
        for p in pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    ]

    assert PILOT_ANALYSES_PATH.is_file()
    assert any(PILOT_ANALYSES_PATH.resolve().is_relative_to(root) for root in roots), (
        f"{PILOT_ANALYSES_PATH} is outside the shipped package tree, so `seed` would "
        f"find no analyses in any non-editable install"
    )


def test_every_pilot_roof_has_an_analysis() -> None:
    """A roof missing from this file falls back to the regional band. That is a
    correct behaviour and a wrong outcome for a roof the pipeline has run over,
    and nothing else in the stack would notice."""
    analysed = {row["building_id"] for row in ROWS}
    expected = {roof.building_id for roof in PILOT_ROOFS}
    assert analysed == expected, (
        f"missing: {expected - analysed}, unexpected: {analysed - expected}"
    )


def test_the_file_on_disk_is_what_the_loader_returns() -> None:
    """The loader is the only reader `seed_pilot` and the demo bundle share.
    A shape it silently tolerates is a shape they would silently disagree on."""
    raw = json.loads(PILOT_ANALYSES_PATH.read_text(encoding="utf-8"))
    assert raw == ROWS
    assert isinstance(raw, list) and raw


def test_every_band_overlaps_the_published_range() -> None:
    """PRD 10's yield criterion, asserted rather than eyeballed.

    Overlap, not containment: the pvlib band is a conservative-to-expected pair
    and the published band is a regional average, so they are not the same kind
    of interval and demanding one sit inside the other would be a stricter test
    than the PRD asks for — and a wrong one.
    """
    band = load_assumptions().specific_yield
    for row in ROWS:
        lo = row["annual_yield_kwh_per_kwp_lo"]
        hi = row["annual_yield_kwh_per_kwp_hi"]
        assert lo <= hi, f"{row['building_id']}: band is inverted"
        assert lo <= float(band.hi) and hi >= float(band.lo), (
            f"{row['building_id']}: pvlib band {lo}-{hi} does not overlap the published "
            f"band {band.lo}-{band.hi}. PRD 10: that is evidence the physics is wrong, "
            f"not a reason to widen the band."
        )


def test_the_rows_load_into_the_shape_the_api_reads_back() -> None:
    """`seed_pilot` writes these and the repository reads them out as `YieldRow`.
    Between those two points sits a column list nobody type-checks, so the round
    trip is asserted here."""
    for row in ROWS:
        assert row["id"] == f"{row['building_id']}:{row['version']}"
        assert row["annual_yield_kwh_per_kwp_source"] == "inferred"
        assert 0.0 < row["annual_yield_kwh_per_kwp_confidence"] <= 1.0
        assert set(row["monthly_yield_json"]) == {f"{m:02d}" for m in range(1, 13)}

        YieldRow(
            version=row["version"],
            value=row["annual_yield_kwh_per_kwp"],
            lo=row["annual_yield_kwh_per_kwp_lo"],
            hi=row["annual_yield_kwh_per_kwp_hi"],
            source=row["annual_yield_kwh_per_kwp_source"],
            confidence=row["annual_yield_kwh_per_kwp_confidence"],
        )


def test_the_assumptions_are_documented_alongside_every_figure() -> None:
    """FR-2.4. A yield number whose loss chain is not recorded cannot be argued
    with, and `irradiance_source` is the field that stops a scaled clear-sky year
    being mistaken for real weather."""
    for row in ROWS:
        losses = row["loss_assumptions_json"]
        assert losses["irradiance_source"] in {"TMY", "CLEARSKY_SCALED"}
        assert 0.0 < losses["total_retained"] < 1.0
        for key in ("tilt_deg", "azimuth_deg", "poa_kwh_per_m2", "analysed_on"):
            assert key in losses, f"{row['building_id']} does not record {key}"


class _FakeCursor:
    def __init__(self, log: list[tuple[str, Any]]) -> None:
        self._log = log

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self._log.append((sql, params))

    def executemany(self, sql: str, params: Any = None) -> None:
        self._log.append((sql, params))


class _FakeConn:
    """Just enough psycopg to see which statements `seed_pilot` issues."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.statements)

    def commit(self) -> None:
        return None


def test_seeding_the_pilot_writes_its_analyses() -> None:
    """The whole point of committing the file: `docker compose up` gives per-roof
    yields without anyone first building the multi-gigabyte CUDA image."""
    conn = _FakeConn()
    counts = seed_pilot(conn)

    assert counts["roof_analyses"] == len(PILOT_ROOFS)
    written = [s for s in conn.statements if "roof_analyses" in s[0]]
    assert len(written) == len(PILOT_ROOFS)


def test_seeding_imported_roofs_writes_no_borrowed_analysis() -> None:
    """`roofs-import` tells the operator to run `yield` next because the roofs it
    just wrote have no analysis. That sentence stays true only because
    `seed_pilot` filters the committed rows to the roofs it was actually given —
    otherwise an imported ward would inherit a pilot roof's physics."""
    conn = _FakeConn()
    counts = seed_pilot(conn, roofs=())

    assert counts["roof_analyses"] == 0
    assert not [s for s in conn.statements if "roof_analyses" in s[0]]
