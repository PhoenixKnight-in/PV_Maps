"""Where the panels actually go — a real array layout, not an area ÷ constant.

`sizing.capacity` converts usable area to kWp through `area_per_kwp_m2`
(9-12 m2/kWp), and the assumptions pack is explicit that this is a placeholder:

    "Replace with measured module dimensions and a real array layout before
     quoting a roof maximum to an installer."

This module is that replacement for the *visual* answer. It packs actual module
rectangles into the usable roof so a household can see the panels on their own
roof rather than being told a number of square metres. The rectangles are
geometry, not a quote: nothing here knows about structural load, cable runs,
inverter placement or the shading of the neighbour's water tank.

Everything is computed in UTM 44N, where a metre is a metre. Packing in degrees
would stretch every row by sec(latitude) and produce a layout that looks right
and does not fit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pvmaps.crs import UTM_44N

if TYPE_CHECKING:  # pragma: no cover
    from shapely.geometry.base import BaseGeometry

__all__ = ["ArrayLayout", "PanelSpec", "pack_panels"]


@dataclass(frozen=True, slots=True)
class PanelSpec:
    """One module, and the geometry of putting it on a flat roof.

    Defaults are a common Indian residential mono-PERC module. They are stated
    here rather than hidden in the packing loop because an installer will want to
    change exactly these four numbers.
    """

    width_m: float = 1.722
    """Long edge. Laid ALONG the row."""

    height_m: float = 1.134
    """Short edge. Runs up the tilted plane."""

    watts: int = 400
    tilt_deg: float = 15.0
    """Matches the tilt the pvlib run selected for the pilot roofs, so the
    generation figure and the picture describe the same array."""

    @property
    def projected_depth_m(self) -> float:
        """Footprint depth of a tilted module, looked at from above."""
        return self.height_m * math.cos(math.radians(self.tilt_deg))

    def row_pitch_m(self, latitude_deg: float) -> float:
        """Row-to-row spacing that keeps the back row unshaded at winter noon.

        Winter solstice is the binding case: the sun is lowest, so the shadow is
        longest. Solar noon altitude is `90 - |lat| - 23.45`, and a module tilted
        `t` with height `h` casts `h*sin(t)/tan(altitude)` behind itself.

        Sized for noon rather than for the whole day on purpose. Guaranteeing no
        inter-row shading at 9am in December would roughly double the pitch and
        halve the array, which is not how rooftop systems are actually built.
        """
        altitude = 90.0 - abs(latitude_deg) - 23.45
        if altitude <= 5.0:
            # Far from the tropics this becomes unbounded. The pilot is at 12.9 N
            # so this is a guard, not a case we expect to hit.
            altitude = 5.0
        shadow = self.height_m * math.sin(math.radians(self.tilt_deg)) / math.tan(
            math.radians(altitude)
        )
        return self.projected_depth_m + shadow


@dataclass(frozen=True, slots=True)
class ArrayLayout:
    panels: tuple[BaseGeometry, ...]
    """Module rectangles in EPSG:4326, ready to draw."""

    spec: PanelSpec
    orientation_deg: float
    """Row bearing, degrees. Rows run along the roof's longest edge."""

    @property
    def count(self) -> int:
        return len(self.panels)

    @property
    def kwp(self) -> float:
        return round(self.count * self.spec.watts / 1000.0, 2)

    def to_geojson(self) -> dict[str, Any]:
        from shapely.geometry import mapping

        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": mapping(p),
                    "properties": {"index": i, "watts": self.spec.watts},
                }
                for i, p in enumerate(self.panels)
            ],
        }


def _dominant_bearing(utm_poly: BaseGeometry) -> float:
    """Angle of the longest edge of the minimum rotated rectangle, in radians.

    Aligning rows to the roof rather than to true north is what makes a layout
    look like something an installer would build. A north-aligned grid on a roof
    that sits at 30 degrees wastes a triangle along every edge.
    """
    rect = utm_poly.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)[:-1]
    if len(coords) < 4:
        return 0.0
    best, best_len = 0.0, -1.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:] + coords[:1], strict=False):
        length = math.hypot(x2 - x1, y2 - y1)
        if length > best_len:
            best_len, best = length, math.atan2(y2 - y1, x2 - x1)
    return best


def pack_panels(
    usable_wgs84: BaseGeometry,
    *,
    latitude_deg: float,
    spec: PanelSpec | None = None,
    walkway_every: int = 4,
    walkway_m: float = 0.6,
    max_panels: int = 4000,
) -> ArrayLayout:
    """Fill a usable roof polygon with module rectangles.

    `usable_wgs84` must ALREADY be net of obstructions and the parapet setback --
    `roofs.usable_roof` is what produces it. Packing the raw footprint would draw
    panels on top of the water tank.

    A module is kept only if it lies ENTIRELY inside the usable polygon. Clipping
    partial modules would let a layout claim half a panel, and half a panel
    generates nothing.
    """
    from shapely.affinity import rotate
    from shapely.geometry import Polygon

    from pvmaps.pipeline.roofs import to_utm, to_wgs84

    s = spec or PanelSpec()
    utm = to_utm(usable_wgs84)
    if utm.is_empty or utm.area <= 0:
        return ArrayLayout(panels=(), spec=s, orientation_deg=0.0)

    theta = _dominant_bearing(utm)
    # Rotate the ROOF flat instead of rotating every candidate module: one
    # transform instead of thousands, and the grid maths stays axis-aligned.
    pivot = utm.centroid
    flat = rotate(utm, -math.degrees(theta), origin=pivot, use_radians=False)

    minx, miny, maxx, maxy = flat.bounds
    pitch = s.row_pitch_m(latitude_deg)
    if pitch <= 0 or s.width_m <= 0:
        return ArrayLayout(panels=(), spec=s, orientation_deg=math.degrees(theta))

    cells: list[BaseGeometry] = []
    row = 0
    y = miny
    while y + s.projected_depth_m <= maxy and len(cells) < max_panels:
        x = minx
        while x + s.width_m <= maxx and len(cells) < max_panels:
            cell = Polygon(
                [
                    (x, y),
                    (x + s.width_m, y),
                    (x + s.width_m, y + s.projected_depth_m),
                    (x, y + s.projected_depth_m),
                ]
            )
            if flat.contains(cell):
                cells.append(cell)
            x += s.width_m
        row += 1
        # A maintenance walkway every few rows. Without one the middle of a large
        # array is unreachable for cleaning, and TN soiling is not negligible --
        # the assumptions pack prices that cleaning.
        y += pitch + (walkway_m if walkway_every and row % walkway_every == 0 else 0.0)

    panels = tuple(
        to_wgs84(rotate(c, math.degrees(theta), origin=pivot, use_radians=False), srid=UTM_44N)
        for c in cells
    )
    return ArrayLayout(panels=panels, spec=s, orientation_deg=math.degrees(theta))
