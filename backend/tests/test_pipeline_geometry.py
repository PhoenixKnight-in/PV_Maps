"""Roof geometry and IoU — the offline plane's arithmetic.

Skipped unless shapely and pyproj are installed. They live in the `pipeline`
dependency group, which the API image deliberately does not carry
(ARCHITECTURE.md 1), so a developer working on the calculation spine will see
these skip and that is correct. They run in the pipeline image and wherever the
pipeline group is installed.

What is actually being defended here is the CRS. `geom.area` on an EPSG:4326
polygon returns square degrees; at Vellore that is wrong by about ten orders of
magnitude, and the result is still a positive float that a dashboard will render
without complaint.
"""

from __future__ import annotations

import math

import pytest

shapely = pytest.importorskip("shapely", reason="pipeline dependency group not installed")
pytest.importorskip("pyproj", reason="pipeline dependency group not installed")

from shapely.geometry import Polygon  # noqa: E402

from pvmaps.pipeline.iou import evaluate, iou  # noqa: E402
from pvmaps.pipeline.roofs import (  # noqa: E402
    MIN_USABLE_FRAGMENT_M2,
    area_m2,
    to_utm,
    usable_roof,
)

VELLORE_LAT = 12.9202
VELLORE_LON = 79.1325


def square(lat: float, lon: float, side_m: float) -> Polygon:
    """A square of `side_m` centred on (lat, lon), in EPSG:4326."""
    half_lat = (side_m / 2) / 111_320.0
    half_lon = (side_m / 2) / (111_320.0 * math.cos(math.radians(lat)))
    return Polygon(
        [
            (lon - half_lon, lat - half_lat),
            (lon + half_lon, lat - half_lat),
            (lon + half_lon, lat + half_lat),
            (lon - half_lon, lat + half_lat),
        ]
    )


# ---------------------------------------------------------------------------
# CRS
# ---------------------------------------------------------------------------


def test_area_is_metres_not_degrees() -> None:
    roof = square(VELLORE_LAT, VELLORE_LON, 10.0)
    assert area_m2(roof) == pytest.approx(100.0, rel=0.01)
    # What the bug looks like, so the test says why it exists.
    assert roof.area < 1e-7, "a 4326 polygon's raw .area is square degrees"


def test_utm_round_trip_preserves_area() -> None:
    roof = square(VELLORE_LAT, VELLORE_LON, 30.0)
    assert to_utm(roof).area == pytest.approx(900.0, rel=0.01)


def test_a_polygon_already_in_utm_is_not_transformed_twice() -> None:
    from pvmaps.crs import UTM_44N

    utm = to_utm(square(VELLORE_LAT, VELLORE_LON, 10.0))
    assert to_utm(utm, srid=UTM_44N).area == pytest.approx(utm.area)


# ---------------------------------------------------------------------------
# Usable area (FR-1.2 to FR-1.4)
# ---------------------------------------------------------------------------


def test_setback_shrinks_the_usable_area() -> None:
    """A 10 m square with a 0.5 m parapet setback leaves 9 x 9 = 81 m2."""
    roof = usable_roof(square(VELLORE_LAT, VELLORE_LON, 10.0), setback_m=0.5)
    assert roof.roof_area_m2 == pytest.approx(100.0, rel=0.01)
    assert roof.usable_area_m2 == pytest.approx(81.0, rel=0.02)
    assert roof.usable_fraction < 1.0


def test_usable_never_exceeds_the_footprint() -> None:
    """The invariant `buildings.ck_usable_within_roof` enforces, checked before
    the row is ever built."""
    roof = usable_roof(square(VELLORE_LAT, VELLORE_LON, 12.0))
    assert roof.usable_area_m2 <= roof.roof_area_m2


def test_an_obstruction_is_subtracted_and_recorded() -> None:
    """FR-1.2 and FR-1.6: the water tank comes out of the area AND is persisted,
    because an unexplained usable area is one the user cannot correct."""
    footprint = square(VELLORE_LAT, VELLORE_LON, 20.0)
    tank = square(VELLORE_LAT, VELLORE_LON, 4.0)

    clear = usable_roof(footprint, setback_m=0.5)
    blocked = usable_roof(footprint, (tank,), setback_m=0.5)

    assert blocked.usable_area_m2 == pytest.approx(clear.usable_area_m2 - 16.0, rel=0.05)
    gj = blocked.obstruction_geojson()
    assert gj is not None
    assert gj["features"][0]["properties"]["area_m2"] == pytest.approx(16.0, rel=0.05)


def test_a_roof_smaller_than_its_setback_has_no_usable_area() -> None:
    """A stairwell head, not an error."""
    roof = usable_roof(square(VELLORE_LAT, VELLORE_LON, 0.8), setback_m=0.5)
    assert roof.usable_area_m2 == pytest.approx(0.0, abs=0.01)
    assert any("setback" in n for n in roof.notes)


def test_slivers_too_small_for_a_module_are_discarded() -> None:
    """An obstruction that cuts a roof in two leaves offcuts. Counting a 2 m2
    fragment is how a usable area becomes optimistic one sliver at a time."""
    footprint = square(VELLORE_LAT, VELLORE_LON, 12.0)
    # A wall across the roof, offset so one side is a thin strip.
    utm = to_utm(footprint)
    minx, miny, maxx, maxy = utm.bounds
    from pvmaps.pipeline.roofs import to_wgs84

    divider = to_wgs84(
        Polygon([(minx, miny + 1.2), (maxx, miny + 1.2), (maxx, maxy), (minx, maxy)])
    )

    roof = usable_roof(footprint, (divider,), setback_m=0.5)
    for piece in getattr(roof.usable, "geoms", [roof.usable]):
        if not piece.is_empty:
            assert area_m2(piece) >= MIN_USABLE_FRAGMENT_M2 - 0.01


def test_shading_allowance_reduces_area_and_says_so() -> None:
    plain = usable_roof(square(VELLORE_LAT, VELLORE_LON, 10.0))
    shaded = usable_roof(square(VELLORE_LAT, VELLORE_LON, 10.0), shading_loss_fraction=0.2)
    assert shaded.usable_area_m2 == pytest.approx(plain.usable_area_m2 * 0.8, rel=0.01)
    assert any("shading" in n for n in shaded.notes)


def test_a_shading_fraction_of_one_is_refused() -> None:
    with pytest.raises(ValueError, match="shading loss"):
        usable_roof(square(VELLORE_LAT, VELLORE_LON, 10.0), shading_loss_fraction=1.0)


# ---------------------------------------------------------------------------
# IoU (PRD 10)
# ---------------------------------------------------------------------------


def test_identical_polygons_score_one() -> None:
    roof = square(VELLORE_LAT, VELLORE_LON, 10.0)
    assert iou(roof, roof) == pytest.approx(1.0)


def test_disjoint_polygons_score_zero() -> None:
    a = square(VELLORE_LAT, VELLORE_LON, 10.0)
    b = square(VELLORE_LAT + 0.01, VELLORE_LON + 0.01, 10.0)
    assert iou(a, b) == pytest.approx(0.0)


def test_a_missed_roof_scores_zero_rather_than_vanishing() -> None:
    """The most common way an IoU number gets flattering is by dropping the
    misses from the denominator."""
    truth = square(VELLORE_LAT, VELLORE_LON, 10.0)
    report = evaluate([(truth, truth), (Polygon(), truth)])
    assert report.n == 2
    assert report.mean == pytest.approx(0.5)
    assert report.worst == 0.0


def test_a_short_evaluation_is_not_reported_as_a_result() -> None:
    """PRD 10 requires 50 roofs. Two perfect scores are not a pass."""
    roof = square(VELLORE_LAT, VELLORE_LON, 10.0)
    report = evaluate([(roof, roof)] * 2)
    assert report.mean == pytest.approx(1.0)
    assert report.meets_criterion is False
    assert "INSUFFICIENT EVIDENCE" in report.verdict


def test_a_below_target_result_says_so_plainly() -> None:
    truth = square(VELLORE_LAT, VELLORE_LON, 10.0)
    poor = square(VELLORE_LAT, VELLORE_LON, 7.0)
    report = evaluate([(poor, truth)] * 50)
    assert report.n == 50
    assert report.mean < 0.75
    assert report.meets_criterion is False
    assert "BELOW TARGET" in report.verdict
    assert "Do not lower the target" in report.verdict


def test_a_passing_result_reports_the_actual_number() -> None:
    truth = square(VELLORE_LAT, VELLORE_LON, 10.0)
    good = square(VELLORE_LAT, VELLORE_LON, 9.6)
    report = evaluate([(good, truth)] * 50)
    assert report.meets_criterion is True
    assert "MEETS CRITERION" in report.verdict
    assert report.to_json()["n"] == 50


# ---------------------------------------------------------------------------
# Importing hand-corrected roofs — build order item 8
# ---------------------------------------------------------------------------


from pvmaps.pipeline.ingest import roofs_from_geojson  # noqa: E402


def feature(geom: Polygon, **properties: object) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [list(geom.exterior.coords)]},
        "properties": properties,
    }


def collection(*features: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


ROOF = collection(
    feature(
        square(VELLORE_LAT, VELLORE_LON, 12.0),
        id="ward2-11",
        display_name="11 Bagayam Road, Vellore",
        ward="Vellore-ward-2",
        confidence=0.7,
    )
)


def test_an_imported_roof_carries_computed_areas_not_claimed_ones() -> None:
    """The areas come from UTM 44N here, never from the file.

    A `roof_area_m2` property in somebody's GeoJSON was computed by whatever drew
    it, in whatever CRS that tool used. Trusting it is how a roof arrives in
    square degrees and still renders.
    """
    lying = collection(
        feature(
            square(VELLORE_LAT, VELLORE_LON, 12.0),
            id="ward2-11",
            display_name="11 Bagayam Road, Vellore",
            roof_area_m2=999_999.0,
            usable_area_m2=999_999.0,
        )
    )
    [roof] = roofs_from_geojson(lying)
    assert roof.roof_area_m2 == pytest.approx(144.0, rel=0.01)
    assert roof.usable_area_m2 < roof.roof_area_m2


def test_an_imported_roof_is_seedable_as_it_stands() -> None:
    """It comes back as the same `PilotRoof` the hand-written pilot uses, so the
    seeder, the table constraints and the demo bundle all see one kind of roof."""
    [roof] = roofs_from_geojson(ROOF)
    assert roof.id == "addr-ward2-11"
    assert roof.building_id == "bldg-ward2-11"
    assert roof.confidence == 0.7
    assert roof.ward == "Vellore-ward-2"
    assert roof.footprint_wkt.startswith("POLYGON ((")
    assert roof.lat == pytest.approx(VELLORE_LAT, abs=1e-4)
    assert roof.lon == pytest.approx(VELLORE_LON, abs=1e-4)
    assert roof.usable_area_m2 <= roof.roof_area_m2


def test_a_marked_obstruction_is_subtracted_and_persisted() -> None:
    """FR-1.2 and FR-1.6 through the import path, not just the geometry helper."""
    tank = feature(
        square(VELLORE_LAT, VELLORE_LON, 3.0),
        building_id="bldg-ward2-11",
        label="water tank",
    )
    [bare] = roofs_from_geojson(ROOF)
    [marked] = roofs_from_geojson(ROOF, collection(tank))

    assert marked.usable_area_m2 < bare.usable_area_m2
    assert marked.obstruction_geojson is not None
    assert marked.obstruction_geojson["features"][0]["properties"]["area_m2"] == pytest.approx(
        9.0, rel=0.05
    )


def test_an_obstruction_may_be_keyed_by_either_id_the_roof_has() -> None:
    """Whoever marked the tank wrote down whichever id they were looking at."""
    tank = square(VELLORE_LAT, VELLORE_LON, 3.0)
    by_building = roofs_from_geojson(ROOF, collection(feature(tank, building_id="bldg-ward2-11")))
    by_address = roofs_from_geojson(ROOF, collection(feature(tank, id="addr-ward2-11")))
    assert by_building[0].usable_area_m2 == by_address[0].usable_area_m2


def test_an_obstruction_on_no_imported_roof_is_an_error() -> None:
    """Dropping it would make that roof look bigger than it is, which is the
    direction of error that reaches a household as a too-large system."""
    stray = feature(square(VELLORE_LAT, VELLORE_LON, 3.0), building_id="bldg-not-here")
    with pytest.raises(ValueError, match="not in this import"):
        roofs_from_geojson(ROOF, collection(stray))


def test_a_shading_allowance_is_applied_on_import() -> None:
    shaded = collection(
        feature(
            square(VELLORE_LAT, VELLORE_LON, 12.0),
            id="ward2-11",
            display_name="11 Bagayam Road, Vellore",
            shading_loss_fraction=0.25,
        )
    )
    [bare] = roofs_from_geojson(ROOF)
    [roof] = roofs_from_geojson(shaded)
    assert roof.usable_area_m2 == pytest.approx(bare.usable_area_m2 * 0.75, rel=0.01)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (collection(feature(square(VELLORE_LAT, VELLORE_LON, 12.0), display_name="x")), "id"),
        (
            collection(feature(square(VELLORE_LAT, VELLORE_LON, 12.0), id="ward2-11")),
            "display_name",
        ),
        (
            collection(
                feature(square(VELLORE_LAT, VELLORE_LON, 12.0), id="ward2-11", display_name="a"),
                feature(square(VELLORE_LAT, VELLORE_LON, 9.0), id="ward2-11", display_name="b"),
            ),
            "duplicate",
        ),
        (
            collection(
                {
                    "type": "Feature",
                    "geometry": {"type": "MultiPolygon", "coordinates": []},
                    "properties": {"id": "ward2-11", "display_name": "a"},
                }
            ),
            "Polygon",
        ),
        ({"type": "Topology"}, "FeatureCollection"),
    ],
    ids=["no_id", "no_display_name", "duplicate_id", "multipolygon", "not_geojson"],
)
def test_input_that_cannot_be_imported_honestly_is_refused(payload: dict, match: str) -> None:
    """Each of these has a quiet version that is worse than the exception: a roof
    written twice, a roof nobody can search for, or half a building discarded."""
    with pytest.raises(ValueError, match=match):
        roofs_from_geojson(payload)
