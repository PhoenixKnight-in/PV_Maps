"""Roof geometry — FR-1.1 to FR-1.6. Offline plane only.

    "Roof segmentation is input infrastructure, not PV Maps' claimed innovation."

Which is why this module is mostly careful arithmetic rather than cleverness. The
two things it must not get wrong:

**The CRS.** Geometry is stored in EPSG:4326 and every area is computed in
EPSG:32644 (UTM 44N, which covers Vellore at 79.13 deg E). Computing an area in
degrees silently inflates it by a factor of roughly 1.2e10 at this latitude, and
the number still looks like a plausible roof if nobody checks the units.

**The usable fraction.** `usable_area_m2` is what survives obstructions and a
parapet setback. It is not the footprint, and the difference is the whole reason
a roof maximum is smaller than a naive area/efficiency calculation.

SAM2 is imported lazily in `propose_masks` only. Everything else here runs with
shapely and pyproj, so the geometry is testable without a GPU — and
`mask_to_polygons` is deliberately separate from the model that produces the
mask.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pvmaps.crs import UTM_44N, WGS84

if TYPE_CHECKING:  # pragma: no cover
    import numpy as np
    from shapely.geometry.base import BaseGeometry

__all__ = [
    "RoofGeometry",
    "area_m2",
    "build_image_predictor",
    "build_mask_generator",
    "mask_to_polygons",
    "masks_at_point",
    "to_utm",
    "usable_roof",
]

PARAPET_SETBACK_M = 0.5
"""Panels cannot sit flush against a parapet: there has to be room to walk and to
avoid the parapet's own shadow at low sun angles. Half a metre is the working
figure for the pilot and it is applied as an inward buffer.

It is a geometric access allowance, not a regulatory one, which is why it lives
here rather than in the rule packs -- nothing downstream values it in rupees.
Array packing (inter-row spacing) is handled separately, in
`sizing.capacity.area_per_kwp_m2`, because that genuinely is an assumption and
belongs in versioned config."""

MIN_USABLE_FRAGMENT_M2 = 4.0
"""After subtracting obstructions a roof breaks into pieces. A 2 m2 offcut behind
a water tank cannot hold a module, and counting it is how a usable-area figure
becomes optimistic one sliver at a time."""


def _transformer(from_srid: int, to_srid: int) -> Any:
    from pyproj import Transformer

    return Transformer.from_crs(f"EPSG:{from_srid}", f"EPSG:{to_srid}", always_xy=True)


def to_utm(geom: BaseGeometry, srid: int = WGS84) -> BaseGeometry:
    """Reproject into UTM 44N so that an area is in square metres."""
    from shapely.ops import transform

    if srid == UTM_44N:
        return geom
    return transform(_transformer(srid, UTM_44N).transform, geom)


def to_wgs84(geom: BaseGeometry, srid: int = UTM_44N) -> BaseGeometry:
    """Back to storage CRS."""
    from shapely.ops import transform

    if srid == WGS84:
        return geom
    return transform(_transformer(srid, WGS84).transform, geom)


def area_m2(geom: BaseGeometry, srid: int = WGS84) -> float:
    """Area in square metres, via UTM 44N.

    Never `geom.area` on a 4326 geometry. That returns square degrees, and at
    Vellore's latitude the number is wrong by about ten orders of magnitude while
    still being a positive float that a dashboard will happily render.
    """
    return float(to_utm(geom, srid).area)


@dataclass(frozen=True, slots=True)
class RoofGeometry:
    """One roof, ready to be written to `buildings`."""

    footprint: BaseGeometry
    """Outline in EPSG:4326 -- the storage CRS."""

    usable: BaseGeometry
    """What survives obstructions and the parapet setback, in EPSG:4326."""

    roof_area_m2: float
    usable_area_m2: float
    obstructions: tuple[BaseGeometry, ...] = field(default_factory=tuple)
    confidence: float = 0.0
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.usable_area_m2 > self.roof_area_m2 + 1e-6:
            raise ValueError(
                f"usable {self.usable_area_m2} m2 exceeds footprint {self.roof_area_m2} m2 -- "
                "this is the invariant buildings.ck_usable_within_roof enforces"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")

    @property
    def usable_fraction(self) -> float:
        if self.roof_area_m2 <= 0:
            return 0.0
        return self.usable_area_m2 / self.roof_area_m2

    def obstruction_geojson(self) -> dict[str, Any] | None:
        """FR-1.6: obstruction geometry is persisted, not just its effect.

        A usable area that cannot be explained is a usable area nobody can
        correct, and FR-1.5 requires it to be correctable.
        """
        from shapely.geometry import mapping

        if not self.obstructions:
            return None
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": mapping(ob),
                    "properties": {"area_m2": round(area_m2(ob), 2)},
                }
                for ob in self.obstructions
            ],
        }


def usable_roof(
    footprint: BaseGeometry,
    obstructions: tuple[BaseGeometry, ...] = (),
    *,
    confidence: float = 0.0,
    setback_m: float = PARAPET_SETBACK_M,
    shading_loss_fraction: float = 0.0,
    notes: tuple[str, ...] = (),
) -> RoofGeometry:
    """FR-1.2 to FR-1.4 — footprint minus obstructions minus a parapet setback.

    The order is deliberate. Setback first, then obstruction subtraction, then
    discard of fragments too small to hold a module: subtracting first and
    buffering after would let the buffer eat into the already-removed obstruction
    footprints and double-count the loss.

    `shading_loss_fraction` is applied to the AREA, not to the yield, and only
    where FR-1.4 says imagery supports it. Applying a visible-shading allowance in
    both places would charge the household for the same shadow twice.
    """
    if not 0.0 <= shading_loss_fraction < 1.0:
        raise ValueError(f"shading loss must be in [0, 1), got {shading_loss_fraction}")

    from shapely.ops import unary_union

    utm_footprint = to_utm(footprint)
    roof_area = float(utm_footprint.area)

    inset = utm_footprint.buffer(-setback_m)
    applied_notes = list(notes)
    if inset.is_empty:
        # A roof smaller than twice the setback has no interior left. That is a
        # real answer for a stairwell head or a tiny outbuilding, not an error.
        applied_notes.append(
            f"footprint too small for a {setback_m} m setback; no usable area remains"
        )

    if obstructions and not inset.is_empty:
        blocked = unary_union([to_utm(ob) for ob in obstructions])
        inset = inset.difference(blocked)

    from shapely.geometry import Polygon

    pieces = _significant_pieces(inset)
    usable_utm = unary_union(pieces) if pieces else Polygon()

    usable_area = float(usable_utm.area) * (1.0 - shading_loss_fraction)
    if shading_loss_fraction:
        applied_notes.append(
            f"visible-shading allowance of {shading_loss_fraction:.0%} applied to usable area"
        )

    return RoofGeometry(
        footprint=footprint,
        usable=to_wgs84(usable_utm),
        roof_area_m2=roof_area,
        usable_area_m2=min(usable_area, roof_area),
        obstructions=obstructions,
        confidence=confidence,
        notes=tuple(applied_notes),
    )


def _significant_pieces(geom: BaseGeometry) -> list[BaseGeometry]:
    """Drop fragments too small to hold a module. See MIN_USABLE_FRAGMENT_M2."""
    if geom.is_empty:
        return []
    parts = list(getattr(geom, "geoms", [geom]))
    return [p for p in parts if p.area >= MIN_USABLE_FRAGMENT_M2]


def mask_to_polygons(
    mask: np.ndarray,
    transform: Any,
    *,
    min_area_px: int = 40,
    simplify_m: float = 0.25,
) -> list[BaseGeometry]:
    """Raster mask → vector polygons in the raster's CRS.

    Separate from the model that produced the mask on purpose: this is the part
    that can be tested with a hand-drawn numpy array, and it is where the
    off-by-one errors actually live.

    `transform` is a rasterio Affine. `simplify_m` removes the single-pixel
    staircase that a raster boundary always has -- at z=19-20 a pixel is roughly
    0.3 m, so a 0.25 m tolerance straightens the staircase without moving a real
    corner.
    """
    import numpy as np
    from rasterio.features import shapes
    from shapely.geometry import shape

    binary = (np.asarray(mask) > 0).astype("uint8")
    polygons: list[BaseGeometry] = []
    for geom, value in shapes(binary, mask=binary.astype(bool), transform=transform):
        if not value:
            continue
        poly = shape(geom)
        if poly.area <= 0:
            continue
        simplified = poly.simplify(simplify_m, preserve_topology=True)
        polygons.append(simplified if simplified.is_valid else poly)

    # Pixel-count floor, applied before simplification changed the area.
    px_area = abs(transform.a * transform.e) if hasattr(transform, "a") else 1.0
    floor = min_area_px * px_area
    return sorted((p for p in polygons if p.area >= floor), key=lambda p: -p.area)


def _build_sam2(checkpoint: str, model_cfg: str) -> Any:
    import torch
    from sam2.build_sam import build_sam2

    device = "cuda" if torch.cuda.is_available() else "cpu"
    return build_sam2(model_cfg, checkpoint, device=device, apply_postprocessing=False)


def build_image_predictor(checkpoint: str, model_cfg: str) -> Any:
    """SAM2 in *prompted* mode. The right tool when the roof location is known.

    `build_mask_generator` segments everything and hopes the roof is in there.
    Over a dense Indian streetscape it is not: on the demo-1 tile the automatic
    generator returned 27 masks for a scene holding hundreds of roofs, keeping
    the high-contrast ones and skipping the rest, and none of them covered the
    roof we were actually asking about.

    But we are never guessing where the roof is -- `addresses.geom` has been
    surveyed, and it is the whole reason the pilot exists. Handing SAM2 that
    point turns "find every object here" into "outline the thing at this
    coordinate", which is the question FR-1.1 actually asks.
    """
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    return SAM2ImagePredictor(_build_sam2(checkpoint, model_cfg))


def masks_at_point(
    predictor: Any, image: np.ndarray, px: float, py: float
) -> list[tuple[np.ndarray, float]]:
    """Masks for whatever sits at one pixel, best predicted IoU first.

    `multimask_output=True` because a point on a rooftop is genuinely ambiguous
    at three scales -- the roof plane, the whole building, the terrace block --
    and SAM2 says so by returning all three with scores. Choosing between them is
    the caller's job and is a question about roofs, not about segmentation.
    """
    import numpy as np

    predictor.set_image(image)
    masks, scores, _ = predictor.predict(
        point_coords=np.array([[px, py]], dtype=np.float32),
        point_labels=np.array([1], dtype=np.int32),
        multimask_output=True,
    )
    order = np.argsort(-np.asarray(scores))
    return [(np.asarray(masks[i]).astype("uint8"), float(scores[i])) for i in order]


def build_mask_generator(checkpoint: str, model_cfg: str) -> Any:
    """Load SAM2 onto the GPU once. The expensive half of `propose_masks`.

    Separate because loading the model costs seconds and segmenting a roof costs
    a fraction of one: a caller working through a ward wants one load and N
    generate calls, not N of each. `pipeline segment` builds this once and reuses
    it across every roof in the run.
    """
    import torch
    from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator
    from sam2.build_sam import build_sam2

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = build_sam2(model_cfg, checkpoint, device=device, apply_postprocessing=False)
    return SAM2AutomaticMaskGenerator(model)


def propose_masks(
    image: np.ndarray,
    checkpoint: str,
    model_cfg: str,
    *,
    generator: Any | None = None,
) -> list[np.ndarray]:
    """FR-1.1 — SAM2 mask proposals. The only GPU-bound function in this module.

    Imported lazily and kept to a handful of lines so that everything around it
    stays runnable and testable on a laptop. `docker/pipeline.Dockerfile` installs
    SAM2 from git; no other image has it, and ARCHITECTURE.md 1 is explicit that
    nothing reachable from an HTTP handler may depend on it.

    Pass `generator` from `build_mask_generator` to reuse a loaded model; omit it
    and one is built for this call alone, which is the convenient shape for a
    single roof and the wrong one for a ward.

    A roof/not-roof classifier still has to rank these proposals (FR-1.1). Until
    it exists, the pilot roofs are hand-corrected, which PRD 9 calls for anyway:
    "Precompute all roof data. Do not run segmentation live on stage."
    """
    gen = generator if generator is not None else build_mask_generator(checkpoint, model_cfg)
    return [record["segmentation"] for record in gen.generate(image)]
