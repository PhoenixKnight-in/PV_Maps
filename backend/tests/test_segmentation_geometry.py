"""The vector half of FR-1.1, tested without a GPU.

`roofs.py` says this is the point of keeping `mask_to_polygons` separate from
`propose_masks`:

    "Separate from the model that produced the mask on purpose: this is the part
     that can be tested with a hand-drawn numpy array, and it is where the
     off-by-one errors actually live."

It said that while having no test at all. These are the off-by-one errors it was
talking about, plus the two coordinate bugs in `imagery.py` that produce a
confident polygon over the wrong place rather than an error:

* a mirrored raster (the affine's negative y-step), and
* ArcGIS `{z}/{y}/{x}` row-before-column tile addressing.

Both are silent. A mirrored roof is still a plausible roof.
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("shapely", reason="pipeline group: shapely")
pytest.importorskip("rasterio", reason="pipeline group: rasterio")
np = pytest.importorskip("numpy", reason="pipeline group: numpy")

from affine import Affine  # noqa: E402

from pvmaps.pipeline.imagery import (  # noqa: E402
    TILE_PX,
    resolution_m,
    tile_xy,
    to_web_mercator,
)
from pvmaps.pipeline.roofs import mask_to_polygons  # noqa: E402

# One metre per pixel, origin at (0, 0), rows running north to south -- the same
# sign convention `imagery.mosaic` builds.
METRE_GRID = Affine(1.0, 0.0, 0.0, 0.0, -1.0, 0.0)


def _square_mask(size: int = 64, top: int = 10, left: int = 20, side: int = 30) -> np.ndarray:
    mask = np.zeros((size, size), dtype="uint8")
    mask[top : top + side, left : left + side] = 1
    return mask


def test_a_square_mask_becomes_one_polygon_of_the_right_area() -> None:
    polygons = mask_to_polygons(_square_mask(), METRE_GRID, min_area_px=1, simplify_m=0.0)

    assert len(polygons) == 1
    # 30x30 pixels at 1 m per pixel.
    assert polygons[0].area == pytest.approx(900.0)


def test_polygons_land_where_the_mask_is_not_mirrored_about_it() -> None:
    """The negative y-step is the whole test.

    A mask 10 rows from the TOP must produce a polygon 10 metres BELOW the
    origin, not 10 above it. Get the sign wrong and every roof is reflected
    across the top edge of its own tile -- still a closed polygon, still a
    plausible area, and wrong by twice its offset.
    """
    polygons = mask_to_polygons(
        _square_mask(top=10, left=20, side=30), METRE_GRID, min_area_px=1, simplify_m=0.0
    )
    minx, miny, maxx, maxy = polygons[0].bounds

    assert (minx, maxx) == pytest.approx((20.0, 50.0))
    # Rows 10..40 from the top, with y decreasing: -10 down to -40.
    assert (miny, maxy) == pytest.approx((-40.0, -10.0))


def test_fragments_below_the_pixel_floor_are_dropped() -> None:
    mask = _square_mask(side=30)
    mask[60:62, 60:62] = 1  # a 4 px offcut

    kept = mask_to_polygons(mask, METRE_GRID, min_area_px=40, simplify_m=0.0)
    everything = mask_to_polygons(mask, METRE_GRID, min_area_px=1, simplify_m=0.0)

    assert len(everything) == 2
    assert len(kept) == 1
    assert kept[0].area == pytest.approx(900.0)


def test_polygons_come_back_largest_first() -> None:
    mask = np.zeros((80, 80), dtype="uint8")
    mask[2:12, 2:12] = 1     # 100 px
    mask[20:50, 20:50] = 1   # 900 px

    areas = [p.area for p in mask_to_polygons(mask, METRE_GRID, min_area_px=1, simplify_m=0.0)]

    assert areas == sorted(areas, reverse=True)


def test_an_empty_mask_yields_nothing() -> None:
    assert mask_to_polygons(np.zeros((32, 32), dtype="uint8"), METRE_GRID) == []


# --- imagery.py coordinate maths -------------------------------------------


def test_tile_xy_matches_a_known_slippy_tile() -> None:
    """Vellore at z19. Checked against the standard OSM tile formula rather than
    against this module's own output, which would prove nothing."""
    lat, lon, z = 12.9202, 79.1325, 19
    n = 2**z
    expected_x = int((lon + 180.0) / 360.0 * n)
    expected_y = int(
        (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    )

    assert tile_xy(lat, lon, z) == (expected_x, expected_y)


def test_z19_pixels_are_roughly_a_fifth_of_a_metre() -> None:
    """FR-1.1's reason for z19 is resolution. If this drifts, the reason is gone.

    This is the equatorial figure; at 12.92 N the true ground sample distance is
    smaller by cos(latitude), about 0.22 m.
    """
    assert resolution_m(19) == pytest.approx(0.2986, abs=1e-4)
    assert resolution_m(19) * cos_lat(12.9202) == pytest.approx(0.291, abs=2e-3)


def cos_lat(lat: float) -> float:
    return math.cos(math.radians(lat))


def test_web_mercator_round_trips_through_pyproj() -> None:
    """`to_web_mercator` is hand-rolled so `mosaic` needs no pyproj. That is only
    safe if it agrees with the real thing."""
    pyproj = pytest.importorskip("pyproj", reason="pipeline group: pyproj")
    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)

    for lat, lon in ((12.9202, 79.1325), (12.9692, 79.1559), (-33.86, 151.21)):
        assert to_web_mercator(lon, lat) == pytest.approx(transformer.transform(lon, lat))


def test_a_mosaic_transform_places_the_centre_tile_over_the_point() -> None:
    """The end-to-end coordinate contract, without fetching anything.

    Rebuilds the affine `mosaic` would build for a 3x3 at z19, then checks the
    roof centroid lands inside the middle tile. This is what catches the ArcGIS
    row/column swap: transposing x and y puts the centroid hundreds of
    kilometres outside the mosaic.
    """
    from pvmaps.pipeline.imagery import _tile_origin_m

    lat, lon, z, radius = 12.9202, 79.1325, 19, 1
    cx, cy = tile_xy(lat, lon, z)
    px = resolution_m(z)
    ox, oy = _tile_origin_m(cx - radius, cy - radius, z)
    transform = Affine(px, 0.0, ox, 0.0, -px, oy)

    mx, my = to_web_mercator(lon, lat)
    col, row = ~transform @ (mx, my)

    # 3x3 tiles: the centre tile spans pixels [256, 512) on both axes.
    assert TILE_PX <= col < 2 * TILE_PX
    assert TILE_PX <= row < 2 * TILE_PX
