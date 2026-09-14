"""Raster imagery for the segmentation plane — FR-1.1's input. Offline only.

`roofs.propose_masks` needs pixels, and until now nothing in the repository could
produce any: `data/` is gitignored (licensed imagery must not be redistributed),
so a fresh clone has a GPU function with nothing to point it at. This module is
that missing half.

Tiles come from the SAME template the browser map uses, which matters more than
it looks. `web/src/components/RoofMap.jsx` renders Esri World Imagery at z19 and
asks the household to confirm the roof outline drawn over it. If segmentation ran
against different pixels, a household could correct an outline against one image
while the model had been reading another, and the disagreement would be invisible
to everyone.

    ARCHITECTURE.md 9.1 — this is the offline plane. Nothing here may be
    reachable from an HTTP handler, and nothing here runs during a demo.

Tiles are cached under `data/imagery/` and re-read from there forever after. The
cache is the point: it is what lets the GPU pass run with the network off, and it
keeps a re-run from hammering somebody else's tile server.

LICENSING. Esri World Imagery is keyless but it is not ours. Cached tiles stay in
`data/`, which `.gitignore` excludes for exactly this reason. Do not commit them,
do not redistribute them, and serve your own raster before shipping this beyond a
pilot.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    import numpy as np

__all__ = [
    "DEFAULT_TILE_TEMPLATE",
    "DEFAULT_ZOOM",
    "TILE_PX",
    "WEB_MERCATOR",
    "mosaic",
    "resolution_m",
    "tile_xy",
    "to_web_mercator",
    "to_wgs84_polygons",
]

WEB_MERCATOR = 3857
TILE_PX = 256
_EARTH_CIRCUMFERENCE_M = 2 * math.pi * 6378137.0
_ORIGIN_M = _EARTH_CIRCUMFERENCE_M / 2.0

DEFAULT_TILE_TEMPLATE = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)
"""Note `{z}/{y}/{x}` — row before column. ArcGIS orders it that way and XYZ
tile servers do not. Swapping the two yields a real tile of somewhere else
entirely, which is the kind of bug that produces a confident mask over the wrong
continent rather than an error."""

DEFAULT_ZOOM = 19
"""FR-1.1 works the imagery at z19-20. `RoofMap` opens at 19 and the same reason
applies here: at z17 a 10 m terrace is about nine pixels across, and SAM2 cannot
segment what is not resolved. At 12.92 N a z19 pixel is about 0.22 m."""


def tile_xy(lat: float, lon: float, z: int) -> tuple[int, int]:
    """(lon, lat) → the slippy-map tile column and row containing it."""
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _tile_origin_m(x: int, y: int, z: int) -> tuple[float, float]:
    """Top-left corner of a tile, in EPSG:3857 metres."""
    span = _EARTH_CIRCUMFERENCE_M / 2**z
    return -_ORIGIN_M + x * span, _ORIGIN_M - y * span


def resolution_m(z: int) -> float:
    """Ground sample distance at the equator, metres per pixel."""
    # float(): `int ** int` widens to Any under strict mypy, because the operator
    # returns float for a negative exponent.
    return _EARTH_CIRCUMFERENCE_M / float(2**z * TILE_PX)


def _fetch(url: str, cache: Path, timeout: float) -> bytes:
    """One tile, from the cache if it is there and from the network if not."""
    if cache.exists() and cache.stat().st_size > 0:
        return cache.read_bytes()

    import requests

    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "pvmaps-pipeline/0.1 (Vellore rooftop PV pilot)"},
    )
    response.raise_for_status()
    payload = response.content
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(payload)
    return payload


def mosaic(
    lat: float,
    lon: float,
    *,
    z: int = DEFAULT_ZOOM,
    radius_tiles: int = 1,
    data_dir: Path = Path("/data"),
    template: str = DEFAULT_TILE_TEMPLATE,
    timeout: float = 30.0,
) -> tuple[np.ndarray, Any]:
    """Stitch the tiles around a point into one georeferenced RGB array.

    Returns `(image, transform)` where `image` is HxWx3 uint8 and `transform` is
    a rasterio `Affine` in **EPSG:3857** — which is what `roofs.mask_to_polygons`
    means by "the raster's CRS". Reproject the polygons it returns to 4326 before
    storing or comparing them; `roofs.to_wgs84` will not do it for you, because it
    assumes UTM.

    `radius_tiles=1` gives a 3x3 mosaic, 768 px square, about 170 m on a side at
    z19 and this latitude. That comfortably contains a domestic roof with context
    around it, and context is not optional: SAM2's automatic generator needs to
    see where the roof stops.
    """
    import io

    import numpy as np
    from affine import Affine
    from PIL import Image

    cx, cy = tile_xy(lat, lon, z)
    xs = list(range(cx - radius_tiles, cx + radius_tiles + 1))
    ys = list(range(cy - radius_tiles, cy + radius_tiles + 1))

    rows = []
    for y in ys:
        row = []
        for x in xs:
            url = template.format(z=z, x=x, y=y)
            cache = Path(data_dir) / "imagery" / f"z{z}" / f"{y}" / f"{x}.jpg"
            with Image.open(io.BytesIO(_fetch(url, cache, timeout))) as img:
                row.append(np.asarray(img.convert("RGB"), dtype="uint8"))
        rows.append(np.hstack(row))
    image = np.vstack(rows)

    px = resolution_m(z)
    ox, oy = _tile_origin_m(min(xs), min(ys), z)
    # Negative y-step: raster rows run north to south while 3857 northing runs
    # the other way. Getting this sign wrong mirrors every polygon about the
    # top edge, and the result still looks like a plausible roof.
    transform = Affine(px, 0.0, ox, 0.0, -px, oy)
    return image, transform


def to_web_mercator(lon: float, lat: float) -> tuple[float, float]:
    """(lon, lat) in degrees → EPSG:3857 metres, matching `mosaic`'s transform."""
    x = _ORIGIN_M * lon / 180.0
    y = _ORIGIN_M * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0)) / math.pi
    return x, y


def to_wgs84_polygons(polygons: list[Any]) -> list[Any]:
    """EPSG:3857 → EPSG:4326, the storage CRS.

    Kept here rather than in `roofs` because 3857 is an artefact of how the
    imagery is tiled, not a fact about roofs. `roofs.to_utm` deliberately knows
    only about 4326 and UTM 44N.
    """
    from pyproj import Transformer
    from shapely.ops import transform as shapely_transform

    project = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True).transform
    return [shapely_transform(project, geom) for geom in polygons]
