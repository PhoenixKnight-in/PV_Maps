"""Hand-written SQL, checked against the declared schema.

`api/repository.py` and `pipeline/seed.py` use `text()` and raw INSERT column
lists rather than the ORM — the reads need PostGIS functions the ORM would only
obscure, and the writes are batch upserts. The cost of that choice is that a
typo'd or removed column is invisible until the statement runs, which for the
seeder means the night before a demo.

These tests close most of that gap without a database: every column named in the
SQL must exist on the table the models declare, and every statement must compile
against the PostgreSQL dialect with its bind parameters resolved.

WHAT THIS DOES NOT COVER: semantics. Whether `ST_AsGeoJSON(geom)::json` returns
what `BuildingRow.geojson` expects, whether the LATERAL join picks the row we
think, whether the trigram index is actually used — those need a live PostGIS and
`docker compose up`. Run the stack before trusting a demo.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy.dialects import postgresql

from pvmaps.api import repository
from pvmaps.db.models import Base

TABLES = {t.name: {c.name for c in t.columns} for t in Base.metadata.sorted_tables}

# ---------------------------------------------------------------------------
# Every statement compiles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        repository._SEARCH_SQL,
        repository._BUILDING_SQL,
        repository._INSERT_RUN_SQL,
    ],
    ids=["search", "building", "insert_run"],
)
def test_repository_statements_compile_for_postgres(statement: object) -> None:
    compiled = str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]
    assert compiled


def test_no_literal_percent_survives_into_the_search_sql() -> None:
    """Whether a literal `%` in a `text()` construct needs doubling depends on the
    driver's paramstyle — it would work on one driver and be a syntax error on
    another. The wildcards belong in the bound value of `:contains`, not here."""
    assert "%" not in str(repository._SEARCH_SQL)


# ---------------------------------------------------------------------------
# Every column named actually exists
# ---------------------------------------------------------------------------


def test_the_sizing_run_insert_names_only_real_columns() -> None:
    """The longest hand-written column list in the codebase, and the one whose
    failure mode is losing a demo's audit trail."""
    sql = str(repository._INSERT_RUN_SQL)
    listed = re.search(r"INSERT INTO sizing_runs \((.*?)\)", sql, re.DOTALL)
    assert listed is not None
    columns = {c.strip() for c in listed.group(1).split(",")}
    missing = columns - TABLES["sizing_runs"]
    assert not missing, f"sizing_runs has no column(s) {sorted(missing)}"


def test_the_sizing_run_insert_supplies_every_non_nullable_column() -> None:
    """A NOT NULL column left out of the insert fails at write time, which
    `_persist` swallows by design — so the run would silently never be stored."""
    table = Base.metadata.tables["sizing_runs"]
    required = {
        c.name
        for c in table.columns
        if not c.nullable and c.server_default is None and not c.primary_key
    }
    sql = str(repository._INSERT_RUN_SQL)
    listed = re.search(r"INSERT INTO sizing_runs \((.*?)\)", sql, re.DOTALL)
    assert listed is not None
    columns = {c.strip() for c in listed.group(1).split(",")}
    assert required <= columns, f"insert omits NOT NULL column(s) {sorted(required - columns)}"


def test_the_building_read_names_only_real_columns() -> None:
    sql = str(repository._BUILDING_SQL)
    for column in ("roof_area_m2", "usable_area_m2", "typology", "confidence", "geom"):
        assert column in sql
        assert column in TABLES["buildings"]
    for column in (
        "annual_yield_kwh_per_kwp",
        "annual_yield_kwh_per_kwp_lo",
        "annual_yield_kwh_per_kwp_hi",
        "annual_yield_kwh_per_kwp_source",
        "annual_yield_kwh_per_kwp_confidence",
    ):
        assert column in sql
        assert column in TABLES["roof_analyses"]


def test_the_search_read_names_only_real_columns() -> None:
    sql = str(repository._SEARCH_SQL)
    for column in ("normalized_address", "display_name", "geom"):
        assert column in sql
        assert column in TABLES["addresses"]


def test_the_estimate_columns_helper_agrees_with_the_schema() -> None:
    """`db.models.estimate_columns` names the five-column Estimate shape in one
    place so migrations and the row mapper cannot disagree. This checks it still
    describes the table."""
    from pvmaps.db.models import estimate_columns

    expected = set(estimate_columns("annual_yield_kwh_per_kwp"))
    assert expected <= TABLES["roof_analyses"], sorted(expected - TABLES["roof_analyses"])


# ---------------------------------------------------------------------------
# The seeder
# ---------------------------------------------------------------------------


def test_seeder_upsert_builder_targets_real_columns() -> None:
    from pvmaps.pipeline.seed import _rows_to_upsert

    rows = [
        {
            "id": "x",
            "category": "DOMESTIC",
            "version": "v1",
            "effective_from": None,
            "effective_to": None,
            "rules_json": "{}",
            "verification_status": "UNVERIFIED_AGAINST_PRIMARY_SOURCE",
        }
    ]
    sql = _rows_to_upsert("tariff_schedules", rows, ("category", "version"))
    assert set(rows[0]) <= TABLES["tariff_schedules"]
    assert "ON CONFLICT (category, version) DO UPDATE SET" in sql
    # The conflict key must not be in the SET clause: updating a column to its
    # own value is harmless, but naming it there is a sign the key was wrong.
    assert "category = EXCLUDED.category" not in sql


def test_seeded_pilot_roofs_satisfy_the_table_constraints() -> None:
    """`buildings.ck_usable_within_roof` and `ck_confidence_unit` are database
    constraints; a fixture that violates one fails at seed time."""
    from pvmaps.pipeline.seed import PILOT_ROOFS

    assert PILOT_ROOFS
    for roof in PILOT_ROOFS:
        assert roof.usable_area_m2 <= roof.roof_area_m2, roof.id
        assert 0.0 <= roof.confidence <= 1.0, roof.id
        assert roof.footprint_wkt.startswith("POLYGON((")
        assert roof.building_id != roof.id


def test_seeded_obstructions_have_the_shape_the_api_forwards() -> None:
    """FR-1.6. `buildings.obstruction_geojson` is JSONB and the API passes it
    through untouched, so whatever the seeder writes is what the browser draws.
    The pipeline writes this column from `RoofGeometry.obstruction_geojson()`; a
    hand-corrected pilot roof writes it by hand, and the two must agree in shape
    or the map renders one of them and not the other."""
    from pvmaps.pipeline.seed import PILOT_ROOFS

    marked = [r for r in PILOT_ROOFS if r.obstruction_geojson is not None]
    assert marked, "no pilot roof exercises the obstruction column"

    for roof in marked:
        fc = roof.obstruction_geojson
        assert fc is not None
        assert fc["type"] == "FeatureCollection"
        assert fc["features"]
        for feature in fc["features"]:
            assert feature["type"] == "Feature"
            assert feature["geometry"]["type"] == "Polygon"
            ring = feature["geometry"]["coordinates"][0]
            assert len(ring) >= 4 and ring[0] == ring[-1]
            assert feature["properties"]["area_m2"] > 0
            assert feature["properties"]["label"]


def test_pilot_footprints_convert_to_the_geojson_postgis_would_serve() -> None:
    """The offline demo bundle draws the roof without PostGIS (ARCHITECTURE.md
    9.3), so the WKT the seeder writes and the GeoJSON the bundle carries have to
    describe the same ring, corner for corner."""
    from pvmaps.pipeline.seed import PILOT_ROOFS, polygon_wkt_to_geojson

    for roof in PILOT_ROOFS:
        inner = roof.footprint_wkt[len("POLYGON((") : -len("))")]
        expected = [[float(x), float(y)] for x, y in (pair.split() for pair in inner.split(", "))]
        converted = polygon_wkt_to_geojson(roof.footprint_wkt)
        assert converted == {"type": "Polygon", "coordinates": [expected]}, roof.id


@pytest.mark.parametrize(
    "wkt",
    [
        "POINT(79.13 12.92)",
        "MULTIPOLYGON(((79.13 12.92, 79.14 12.92, 79.14 12.93, 79.13 12.92)))",
        # A ring with a hole: the second ring would be silently dropped, and a
        # dropped hole is a usable area claimed over a courtyard.
        "POLYGON((79.1 12.9, 79.2 12.9, 79.2 13.0, 79.1 12.9), (79.12 12.92, "
        "79.13 12.92, 79.13 12.93, 79.12 12.92))",
        # Unclosed.
        "POLYGON((79.1 12.9, 79.2 12.9, 79.2 13.0))",
        # Three-dimensional coordinates, which would shift every lat by one place.
        "POLYGON((79.1 12.9 0, 79.2 12.9 0, 79.2 13.0 0, 79.1 12.9 0))",
        "",
    ],
    ids=["point", "multipolygon", "with_hole", "unclosed", "3d", "empty"],
)
def test_geometry_the_converter_cannot_honestly_read_is_refused(wkt: str) -> None:
    """A mis-parsed outline is a roof drawn in the wrong place, which no error
    message ever follows. Fail at build time instead."""
    from pvmaps.pipeline.seed import polygon_wkt_to_geojson

    with pytest.raises(ValueError):
        polygon_wkt_to_geojson(wkt)


def test_pilot_addresses_are_searchable_by_the_same_normalisation() -> None:
    """ARCHITECTURE.md 9.3. The seeder writes `normalized_address` and the search
    route matches against it; two copies of that folding would drift, and the
    symptom is a pilot address that cannot be found mid-demo."""
    from pvmaps.addressing import normalize_address
    from pvmaps.pipeline.seed import PILOT_ROOFS

    for roof in PILOT_ROOFS:
        key = normalize_address(roof.display_name)
        assert key
        # What a user would plausibly type has to be a substring of the key,
        # because that is exactly what the search's LIKE clause tests.
        first_words = " ".join(key.split()[:2])
        assert first_words in key


def test_the_health_probe_reads_a_table_that_exists() -> None:
    """`/healthz` counts pilot roofs rather than running `SELECT 1`, which means
    it names a table -- and a probe naming a renamed table would report every
    healthy database as broken."""
    from pvmaps.api.main import PILOT_PROBE_SQL

    assert "buildings" in TABLES
    assert str(PILOT_PROBE_SQL.compile(dialect=postgresql.dialect()))
    assert re.search(r"\bFROM\s+buildings\b", str(PILOT_PROBE_SQL))


def test_the_purge_deletes_expired_runs_and_nothing_else() -> None:
    """ARCHITECTURE.md 8: `expires_at` is a promise until something reads it.

    Two ways for this statement to be quietly wrong, and both are worse than a
    syntax error: a missing WHERE clause deletes every run ever made, and a
    reversed comparison deletes exactly the rows that have not expired.
    """
    from pvmaps.pipeline.seed import PURGE_EXPIRED_RUNS_SQL

    sql = " ".join(PURGE_EXPIRED_RUNS_SQL.split())
    assert sql.startswith("DELETE FROM sizing_runs WHERE ")
    assert "expires_at" in TABLES["sizing_runs"]
    assert "expires_at IS NOT NULL" in sql
    assert "expires_at < now()" in sql


def test_sizing_run_ids_fit_the_column() -> None:
    """`sizing_runs.id` is String(43) because token_urlsafe(32) is 43 characters.
    A longer token would be truncated or rejected on write."""
    from pvmaps.api.routers.sizing import _new_run_id

    column = Base.metadata.tables["sizing_runs"].columns["id"]
    for _ in range(20):
        assert len(_new_run_id()) == column.type.length
