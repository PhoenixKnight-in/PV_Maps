"""Hand-corrected roof GeoJSON → seedable pilot roofs. Build-order item 8.

    "Add segmentation pipeline and grow the pilot area."

The pilot area grows one hand-checked roof at a time, and this is the door those
roofs come through. `PILOT_ROOFS` in `seed.py` is a literal because the first
three demo roofs were measured by hand before anything existed to read a file;
past that, typing a polygon into a Python tuple is not a workflow.

So the input is what a person actually produces: a GeoJSON FeatureCollection of
roof outlines drawn over imagery, and optionally a second one of obstructions
they marked on those roofs. What comes out is `PilotRoof` values — the same type
`seed_pilot` writes and the same type the demo bundle is generated from, so an
imported roof and a hand-written one cannot end up described differently.

Areas are NOT taken from the file. They are computed here, in UTM 44N, by
`roofs.usable_roof`: a `roof_area_m2` property carried in somebody's GeoJSON is
an area computed by whatever drew it, in whatever CRS that tool used, and that
is exactly the mistake `pvmaps.crs` exists to prevent.

Needs shapely (the `pipeline` group). Nothing here reaches a request handler.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pvmaps.pipeline.roofs import PARAPET_SETBACK_M, usable_roof
from pvmaps.pipeline.seed import PilotRoof

if TYPE_CHECKING:  # pragma: no cover
    from shapely.geometry.base import BaseGeometry

__all__ = ["features_of", "roofs_from_geojson"]

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,50}$")

DEFAULT_CONFIDENCE = 0.6
"""A roof somebody drew by hand over imagery, with no stated confidence.

Not 1.0. The outline is as good as the imagery and the person, the usable
fraction still rests on a setback assumption, and FR-1.4 asks for a confidence
score rather than an assertion. Whoever knows better sets `confidence` in the
file.
"""


def features_of(collection: Any, what: str) -> list[dict[str, Any]]:
    """Accept a FeatureCollection or a bare list of features."""
    if isinstance(collection, dict) and collection.get("type") == "FeatureCollection":
        features = collection.get("features", [])
    elif isinstance(collection, list):
        features = collection
    else:
        raise ValueError(f"{what}: expected a GeoJSON FeatureCollection or a list of features")
    if not isinstance(features, list):
        raise ValueError(f"{what}: 'features' is not a list")
    return features


def _slug(raw: Any, index: int) -> str:
    """The bare key a roof is known by, with either prefix accepted.

    One slug becomes two ids -- `addr-<slug>` and `bldg-<slug>` -- which is the
    pairing `PilotRoof.building_id` already assumes. Accepting either spelling on
    the way in means an obstruction file may key on the building id, which is
    what whoever drew it will naturally have written down.

    The id is how a re-import updates a roof instead of duplicating it, so it has
    to be stable and it has to be the operator's choice, never positional. A roof
    that silently changed id between runs would leave the old row in place, still
    findable by search, still answering with last week's outline.
    """
    if raw is None or str(raw).strip() == "":
        raise ValueError(
            f"feature {index}: properties.id is required. It is the stable key a "
            f"re-import updates on; without it the same roof is written twice."
        )
    slug = str(raw).strip().lower()
    slug = slug.removeprefix("addr-") if slug.startswith("addr-") else slug.removeprefix("bldg-")
    if not _ID.match(slug):
        raise ValueError(
            f"feature {index}: id {raw!r} must be lower-case letters, digits and "
            f"hyphens (it becomes both an address id and a building id)"
        )
    return slug


def _polygon(feature: dict[str, Any], index: int, what: str) -> BaseGeometry:
    from shapely.geometry import shape

    geometry = feature.get("geometry")
    if not geometry:
        raise ValueError(f"{what} {index}: feature has no geometry")
    if geometry.get("type") != "Polygon":
        # A MultiPolygon here is usually one building drawn as two disjoint
        # pieces, or two buildings sharing an id. Both need a person, not a
        # rule: picking the largest part would silently discard half a roof.
        raise ValueError(
            f"{what} {index}: geometry is {geometry.get('type')!r}; only Polygon is "
            f"accepted, so that nothing is silently discarded"
        )
    return shape(geometry)


def _group_obstructions(
    collection: Any, known: set[str]
) -> dict[str, list[BaseGeometry]]:
    """Obstruction features, keyed by the building they sit on.

    An obstruction naming a roof that is not in the import is an error rather
    than a warning. The failure it hides is the expensive direction: the roof is
    written without its water tank, and its usable area — and therefore its
    recommended system size — comes out too big.
    """
    grouped: dict[str, list[BaseGeometry]] = {}
    orphans: list[str] = []
    for index, feature in enumerate(features_of(collection, "obstructions")):
        props = feature.get("properties") or {}
        raw = props.get("building_id") or props.get("roof_id") or props.get("id")
        slug = _slug(raw, index)
        if slug not in known:
            orphans.append(slug)
            continue
        grouped.setdefault(slug, []).append(_polygon(feature, index, "obstruction"))

    if orphans:
        raise ValueError(
            f"obstructions reference roofs that are not in this import: "
            f"{sorted(set(orphans))}. An obstruction dropped on the floor makes a "
            f"roof look bigger than it is."
        )
    return grouped


def roofs_from_geojson(
    footprints: Any,
    obstructions: Any | None = None,
    *,
    setback_m: float = PARAPET_SETBACK_M,
) -> tuple[PilotRoof, ...]:
    """Footprint features (+ optional obstruction features) → `PilotRoof` values.

    Recognised footprint properties, all optional except `id` and
    `display_name`:

        id                      stable key; `addr-` is added if absent
        display_name            what address search matches against
        typology                default "residential"
        confidence              default DEFAULT_CONFIDENCE
        ward                    pilot ward label
        shading_loss_fraction   FR-1.4, applied to AREA (see `usable_roof`)
    """
    parsed: list[tuple[dict[str, Any], BaseGeometry, str]] = []
    seen: set[str] = set()
    for index, feature in enumerate(features_of(footprints, "footprints")):
        props = feature.get("properties") or {}
        slug = _slug(props.get("id"), index)
        if slug in seen:
            raise ValueError(f"duplicate roof id {slug!r} in this import")
        seen.add(slug)
        parsed.append((props, _polygon(feature, index, "footprint"), slug))

    grouped = _group_obstructions(obstructions, seen) if obstructions is not None else {}

    roofs: list[PilotRoof] = []
    for props, footprint, slug in parsed:
        display_name = str(props.get("display_name") or "").strip()
        if not display_name:
            raise ValueError(
                f"addr-{slug}: properties.display_name is required — it is the only "
                f"thing address search has to match on."
            )

        marks = tuple(grouped.get(slug, ()))
        geometry = usable_roof(
            footprint,
            marks,
            confidence=float(props.get("confidence", DEFAULT_CONFIDENCE)),
            setback_m=setback_m,
            shading_loss_fraction=float(props.get("shading_loss_fraction", 0.0)),
        )

        centroid = footprint.centroid
        roofs.append(
            PilotRoof(
                id=f"addr-{slug}",
                display_name=display_name,
                lat=round(float(centroid.y), 7),
                lon=round(float(centroid.x), 7),
                footprint_wkt=footprint.wkt,
                roof_area_m2=round(geometry.roof_area_m2, 2),
                usable_area_m2=round(geometry.usable_area_m2, 2),
                typology=str(props.get("typology", "residential")),
                confidence=geometry.confidence,
                ward=props.get("ward"),
                obstruction_geojson=geometry.obstruction_geojson(),
            )
        )
    return tuple(roofs)
