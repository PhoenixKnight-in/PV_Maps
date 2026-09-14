"""Live roof segmentation, over HTTP, on the GPU.

This service exists because PRD 9's "precompute all roof data, do not run
segmentation live" was written for a five-address pilot, and the product it
describes cannot answer "what about MY roof". Segmenting on demand is the
deliberate reversal of that rule, and the cost is stated plainly: a demo now
depends on a reachable tile server and a working GPU.

It is a SEPARATE service rather than a few functions inside `pvmaps.api` for one
blunt reason -- the API image is 303 MB and this one is 6.8 GB. ARCHITECTURE.md 1
keeps torch off the request path, and that still holds: the API makes an HTTP
call, it does not import SAM2.

The model is loaded ONCE, at startup, into module state. Loading SAM2 per request
costs about four seconds and would make every roof lookup feel broken.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("pvmaps.segmenter")

CHECKPOINT = os.environ.get("SAM2_CHECKPOINT", "/checkpoints/sam2.1_hiera_small.pt")
MODEL_CFG = os.environ.get("SAM2_MODEL_CFG", "configs/sam2.1/sam2.1_hiera_s.yaml")
ZOOM = int(os.environ.get("SEGMENTER_ZOOM", "19"))

MIN_ROOF_M2 = float(os.environ.get("SEGMENTER_MIN_M2", "15"))
MAX_ROOF_M2 = float(os.environ.get("SEGMENTER_MAX_M2", "5000"))
"""The plausible-roof window used to rank candidates.

SAM2 returns the same point at three nested scales -- on the VIT tile that was a
courtyard kiosk (235 m2), a wing (324 m2) and the whole complex (4167 m2). Its
own confidence is no help in choosing: the complex outline, which was the only
one a human would call "the building", scored 0.069 against the kiosk's 0.814.

So the window is the ranking signal and the score is not. 15 m2 is below any roof
worth a panel; 5000 m2 is above any single Indian rooftop and catches the failure
where SAM2 returns a city block.
"""

_state: dict[str, Any] = {}


class RoofRequest(BaseModel):
    lat: float = Field(ge=-85.0, le=85.0)
    lon: float = Field(ge=-180.0, le=180.0)
    zoom: int = Field(default=ZOOM, ge=17, le=20)


class Candidate(BaseModel):
    model_config = {"frozen": True}

    geometry: dict[str, Any]
    """GeoJSON Polygon, EPSG:4326."""

    area_m2: float
    sam2_score: float
    plausible: bool
    """True when the area falls inside the roof window. The client draws the
    best plausible candidate and offers the rest; nothing is discarded, because
    a roof genuinely outside the window should still be selectable by hand."""


class PanelLayout(BaseModel):
    """Where the modules actually go, for the chosen outline.

    Computed only for the chosen candidate: packing all three scales would mean
    three array layouts on screen, and the largest of them is usually a city
    block. Re-requesting after the user picks a different outline is cheap --
    the imagery is cached and SAM2 is not re-run.
    """

    model_config = {"frozen": True}

    usable_geometry: dict[str, Any] | None
    """Footprint minus the parapet setback, in EPSG:4326. This is the area the
    panels are packed into, and it is smaller than `Candidate.geometry`."""

    usable_area_m2: float
    panels: dict[str, Any]
    """GeoJSON FeatureCollection, one Polygon per module."""

    panel_count: int
    array_kwp: float
    panel_watts: int
    tilt_deg: float
    row_pitch_m: float


class RoofResponse(BaseModel):
    lat: float
    lon: float
    zoom: int
    candidates: list[Candidate]
    layout: PanelLayout | None = None
    chosen: int | None
    """Index into `candidates`, or None when SAM2 found nothing at the point.

    FR-1.5: this is a proposal the user may overrule, which is why every
    candidate is returned rather than only this one.
    """

    source: str = "SAM2_POINT_PROMPTED_LIVE"
    warning: str | None = None


app = FastAPI(title="PV Maps segmenter", version="0.1.0")


@app.on_event("startup")
def _load_model() -> None:
    """Fail loudly at startup rather than on the first user request."""
    from pvmaps.pipeline.roofs import build_image_predictor

    log.warning("loading SAM2 from %s", CHECKPOINT)
    _state["predictor"] = build_image_predictor(CHECKPOINT, MODEL_CFG)

    import torch

    _state["device"] = (
        torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    )
    log.warning("segmenter ready on %s", _state["device"])


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "status": "ok" if "predictor" in _state else "loading",
        "device": _state.get("device"),
        "checkpoint": os.path.basename(CHECKPOINT),
    }


def _rank(area: float) -> tuple[int, float]:
    """Sort key: plausible roofs first, then largest.

    Largest-within-window rather than closest-to-some-average, because the
    nested scales run small-to-large and the human answer to "which of these is
    the building" is almost always the biggest one that is still a building. The
    kiosk inside the VIT courtyard is a real object and a wrong answer.
    """
    return (0 if MIN_ROOF_M2 <= area <= MAX_ROOF_M2 else 1, -area)


@app.post("/segment", response_model=RoofResponse)
def segment(req: RoofRequest) -> RoofResponse:
    if "predictor" not in _state:
        raise HTTPException(status_code=503, detail="model still loading")

    from shapely.geometry import Point, mapping

    from pvmaps.pipeline.imagery import mosaic, to_web_mercator, to_wgs84_polygons
    from pvmaps.pipeline.roofs import area_m2, mask_to_polygons, masks_at_point

    try:
        image, transform = mosaic(req.lat, req.lon, z=req.zoom, radius_tiles=1)
    except Exception as exc:
        # The tile server is the one dependency this service cannot fake, and
        # "no imagery" is a different answer from "no roof here".
        raise HTTPException(status_code=502, detail=f"imagery unavailable: {exc}") from exc

    centre = Point(*to_web_mercator(req.lon, req.lat))
    px, py = ~transform @ (centre.x, centre.y)

    found = []
    for mask, score in masks_at_point(_state["predictor"], image, px, py):
        for poly in mask_to_polygons(mask, transform):
            if not poly.contains(centre):
                continue
            wgs = to_wgs84_polygons([poly])[0]
            found.append((area_m2(wgs), float(score), wgs))

    if not found:
        return RoofResponse(
            lat=req.lat,
            lon=req.lon,
            zoom=req.zoom,
            candidates=[],
            chosen=None,
            warning="Nothing segmentable at this point. Try dropping the pin on the roof itself.",
        )

    found.sort(key=lambda f: _rank(f[0]))
    candidates = [
        Candidate(
            geometry=mapping(geom),
            area_m2=round(area, 2),
            sam2_score=round(score, 4),
            plausible=MIN_ROOF_M2 <= area <= MAX_ROOF_M2,
        )
        for area, score, geom in found
    ]

    chosen = 0 if candidates[0].plausible else None
    warning = None
    if chosen is None:
        warning = (
            f"Every outline here is outside {MIN_ROOF_M2:.0f}-{MAX_ROOF_M2:.0f} m². "
            "Pick one by hand or move the pin."
        )

    layout = None
    if chosen is not None:
        layout = _layout_for(found[chosen][2], req.lat)

    return RoofResponse(
        lat=req.lat,
        lon=req.lon,
        zoom=req.zoom,
        candidates=candidates,
        chosen=chosen,
        layout=layout,
        warning=warning,
    )


def _layout_for(footprint: Any, latitude: float) -> Any:
    """Usable area and module rectangles for one outline.

    The setback is applied HERE rather than in the packer so that the usable
    polygon is returned too: a household that sees panels stop half a metre short
    of the edge should be able to see the boundary that made them stop.
    """
    from pvmaps.pipeline.layout import PanelSpec, pack_panels
    from pvmaps.pipeline.roofs import area_m2, usable_roof

    geom = usable_roof(footprint)
    if geom.usable.is_empty:
        return None

    spec = PanelSpec()
    array = pack_panels(geom.usable, latitude_deg=latitude, spec=spec)
    return PanelLayout(
        usable_geometry=_mapping(geom.usable),
        usable_area_m2=round(area_m2(geom.usable), 2),
        panels=array.to_geojson(),
        panel_count=array.count,
        array_kwp=array.kwp,
        panel_watts=spec.watts,
        tilt_deg=spec.tilt_deg,
        row_pitch_m=round(spec.row_pitch_m(latitude), 3),
    )


def _mapping(geom: Any) -> dict[str, Any]:
    from shapely.geometry import mapping

    return dict(mapping(geom))
