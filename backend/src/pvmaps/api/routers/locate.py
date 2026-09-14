"""Find any address, then measure the roof under it.

This is the route that breaks the five-address pilot open. Two steps, kept
separate because they fail for different reasons and the UI has to say which:

    GET  /v1/geocode?q=...     address  -> coordinates      (Nominatim)
    POST /v1/roof-at           point    -> roof outlines    (SAM2, on the GPU)

Both are live network calls, which ARCHITECTURE.md 9.3 forbade for the demo. That
rule bought a stage-proof demo at the price of a product that could only answer
for five addresses. The trade has been made deliberately; `/healthz` on each
dependency is what tells you it has gone wrong, rather than a blank map.
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(tags=["locate"])

NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
SEGMENTER_URL = os.environ.get("SEGMENTER_URL", "http://segmenter:8100")

CONTACT = os.environ.get("NOMINATIM_CONTACT", "pvmaps-pilot")
"""Nominatim's usage policy requires an identifying User-Agent naming a real
contact. Sending a default python-httpx agent is how a project gets its IP
blocked mid-demo, so this is not optional politeness."""

COUNTRY_CODES = os.environ.get("GEOCODE_COUNTRY_CODES", "in")
"""India only, by default. PRD 11 scopes the product to Tamil Nadu; a geocoder
that cheerfully resolves "Springfield" would put a US suburb on screen with an
INR tariff attached to it."""


class GeocodeHit(BaseModel):
    model_config = {"frozen": True}

    display_name: str
    lat: float
    lon: float
    kind: str | None = None
    """Nominatim's `type` -- house, residential, commercial. Advisory only."""

    matched_query: str | None = None
    """Set when the hit came from a BROADENED query rather than what was typed.

    The UI has to say so. A household that typed their apartment name and is
    shown their street deserves to know the pin is the street, not the building
    -- and that they should move it onto their own roof.
    """


_GLUED = ("nagar", "puram", "palayam", "kuppam", "pettai", "pakkam", "colony")
"""Place-name suffixes that get written both glued and spaced.

"Gandhinagar" returns nothing and "Gandhi Nagar" returns three hits. OSM stores
one spelling and Indian addresses are written with either, so splitting these is
the difference between a working search and a dead end.
"""

_MAX_VARIANTS = 4
"""Nominatim asks for at most one request per second, and this runs per
keystroke-batch. Four is enough to reach "locality, city" from a full postal
address without turning one search into a rate-limit ban."""


def _variants(q: str) -> list[str]:
    """Progressively broader forms of an address, most specific first.

    Nominatim is unforgiving about exactly the parts of an Indian address least
    likely to be in OSM -- the flat, the building name, the ordinal cross street.
    Measured 2026-09-14:

        "3rd East Cross Road, SM Apartment Gandhinagar,Vellore"  -> 0 hits
        "East Cross Road Gandhi Nagar Vellore"                   -> 2 hits
        "Gandhi Nagar Vellore"                                   -> 3 hits

    So rather than returning nothing, unglue the suffixes and drop the leading
    components one at a time. The caller keeps whichever form answered first and
    tells the user it broadened.
    """
    seen: list[str] = []

    def add(candidate: str) -> None:
        c = " ".join(candidate.replace(",", " ").split()).strip()
        if len(c) >= 3 and c.lower() not in {x.lower() for x in seen}:
            seen.append(c)

    add(q)

    unglued = q
    for suffix in _GLUED:
        # Keep the prefix and insert a space: "Gandhinagar" -> "Gandhi nagar".
        # The capture group is not optional -- dropping it collapses the token to
        # the bare suffix and searches for every "nagar" in India.
        unglued = re.sub(rf"(?i)\b([a-z]{{3,}}?){suffix}\b", r"\1 " + suffix, unglued)
    add(unglued)

    # Drop leading comma-separated segments: in Indian addresses the flat and
    # building name come first and are the least likely to be mapped.
    parts = [p for p in (x.strip() for x in unglued.split(",")) if p]
    for i in range(1, len(parts)):
        add(", ".join(parts[i:]))

    return seen[:_MAX_VARIANTS]


class RoofRequest(BaseModel):
    lat: float = Field(ge=-85.0, le=85.0)
    lon: float = Field(ge=-180.0, le=180.0)
    zoom: int = Field(default=19, ge=17, le=20)


async def _search(client: httpx.AsyncClient, q: str, limit: int) -> list[dict[str, Any]]:
    r = await client.get(
        NOMINATIM_URL,
        params={
            "q": q,
            "format": "jsonv2",
            "limit": str(limit),
            "countrycodes": COUNTRY_CODES,
            "addressdetails": "0",
        },
        headers={"User-Agent": f"PVMaps/0.1 ({CONTACT})"},
    )
    r.raise_for_status()
    payload = r.json()
    return list(payload) if isinstance(payload, list) else []


@router.get("/geocode", response_model=list[GeocodeHit])
async def geocode(
    q: str = Query(min_length=3, max_length=200),
    limit: int = Query(default=6, ge=1, le=10),
) -> list[GeocodeHit]:
    """Resolve a free-text address to coordinates, broadening if it finds nothing.

    Nominatim's ranking is better than anything worth reimplementing, so the
    first variant that answers wins and the rest are not tried. A hit from a
    broadened query carries `matched_query` so the UI can say the pin is the
    street rather than the building.
    """
    variants = _variants(q)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            for attempt, candidate in enumerate(variants):
                payload = await _search(client, candidate, limit)
                if payload:
                    broadened = attempt > 0
                    return [
                        GeocodeHit(
                            display_name=str(h["display_name"]),
                            lat=float(h["lat"]),
                            lon=float(h["lon"]),
                            kind=h.get("type"),
                            matched_query=candidate if broadened else None,
                        )
                        for h in payload
                    ]
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="Address lookup is unreachable. You can still tap the roof on the map.",
        ) from exc

    return []


@router.post("/roof-at")
async def roof_at(body: RoofRequest) -> dict[str, Any]:
    """Segment the roof under a point, live, on the GPU.

    A proxy rather than an implementation: torch must not enter the request-path
    image (ARCHITECTURE.md 1), so the heavy work happens in `pvmaps.segmenter`
    and this route only forwards. The timeout is generous because a cold tile
    cache means nine HTTPS fetches before SAM2 even starts.
    """
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(f"{SEGMENTER_URL}/segment", json=body.model_dump())
            r.raise_for_status()
            return dict(r.json())
    except httpx.HTTPStatusError as exc:
        detail = "Roof measurement failed."
        if exc.response.status_code == 502:
            detail = "Satellite imagery is unavailable for this location right now."
        elif exc.response.status_code == 503:
            detail = "The roof measurement service is still starting. Try again shortly."
        raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="The roof measurement service is unreachable.",
        ) from exc
