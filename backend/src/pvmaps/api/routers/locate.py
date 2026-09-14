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

import asyncio
import os
import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(tags=["locate"])

NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
SEGMENTER_URL = os.environ.get("SEGMENTER_URL", "http://segmenter:8100")

MAPPLS_CLIENT_ID = os.environ.get("MAPPLS_CLIENT_ID", "").strip()
MAPPLS_CLIENT_SECRET = os.environ.get("MAPPLS_CLIENT_SECRET", "").strip()
MAPPLS_REST_KEY = os.environ.get("MAPPLS_REST_KEY", "").strip()

CONTACT = os.environ.get("NOMINATIM_CONTACT", "pvmaps-pilot")
"""Nominatim's usage policy requires an identifying User-Agent naming a real
contact. Sending a default python-httpx agent is how a project gets its IP
blocked mid-demo, so this is not optional politeness."""

COUNTRY_CODES = os.environ.get("GEOCODE_COUNTRY_CODES", "in")
"""India only, by default. PRD 11 scopes the product to Tamil Nadu; a geocoder
that cheerfully resolves "Springfield" would put a US suburb on screen with an
INR tariff attached to it."""

_mappls_token: str | None = None
_mappls_token_expires_at: float = 0.0
_mappls_lock = asyncio.Lock()


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


_BUILDINGS_RE = re.compile(
    r"(?i)\b[A-Za-z0-9\s-]{1,20}(?:Apartment|Apartments|Apt|Flats|Flat|Villa|Villas|Illam|Bhavan|House|Residency|Towers|Enclave)\b,?\s*"
)
_CAREOF_RE = re.compile(r"(?i)\b[sSwWdD]/[oO]\.[^,]+,\s*")


def _variants(q: str) -> list[str]:
    """Progressively broader forms of an address, most specific first.

    Nominatim is unforgiving about exactly the parts of an Indian address least
    likely to be in OSM -- the flat, the building name, the ordinal cross street.
    """
    seen: list[str] = []

    def add(candidate: str) -> None:
        c = " ".join(candidate.replace(",", " ").split()).strip()
        if len(c) >= 3 and c.lower() not in {x.lower() for x in seen}:
            seen.append(c)

    add(q)

    # Clean building names and care-of prefixes that never exist in public OSM
    cleaned = _CAREOF_RE.sub("", q)
    cleaned = _BUILDINGS_RE.sub("", cleaned)

    unglued = cleaned
    for suffix in _GLUED:
        # Keep the prefix and insert a space: "Gandhinagar" -> "Gandhi nagar".
        unglued = re.sub(rf"(?i)\b([a-z]{{3,}}?){suffix}\b", r"\1 " + suffix, unglued)
    add(unglued)

    # Drop leading comma-separated segments: in Indian addresses the flat and
    # building name come first and are the least likely to be mapped.
    parts = [p.strip() for p in unglued.split(",") if p.strip()]
    for i in range(1, len(parts)):
        sub = ", ".join(parts[i:])
        if len(sub.split()) > 1:
            add(sub)

    return seen[:_MAX_VARIANTS]


class RoofRequest(BaseModel):
    lat: float = Field(ge=-85.0, le=85.0)
    lon: float = Field(ge=-180.0, le=180.0)
    zoom: int = Field(default=19, ge=17, le=20)


async def _get_mappls_token(client: httpx.AsyncClient) -> str | None:
    """Fetch or return cached OAuth2 access token for MapmyIndia / Mappls."""
    global _mappls_token, _mappls_token_expires_at
    if not (MAPPLS_CLIENT_ID and MAPPLS_CLIENT_SECRET):
        return None

    if _mappls_token and time.time() < _mappls_token_expires_at:
        return _mappls_token

    async with _mappls_lock:
        if _mappls_token and time.time() < _mappls_token_expires_at:
            return _mappls_token
        try:
            r = await client.post(
                "https://outpost.mappls.com/api/security/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": MAPPLS_CLIENT_ID,
                    "client_secret": MAPPLS_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            data = r.json()
            token = data.get("access_token")
            expires_in = float(data.get("expires_in", 86400))
            if token:
                _mappls_token = token
                _mappls_token_expires_at = time.time() + expires_in - 60
                return token
        except Exception:
            return None
    return None


async def _search_mappls(client: httpx.AsyncClient, q: str, limit: int) -> list[GeocodeHit]:
    """Query MapmyIndia (Mappls) for hyper-local Indian house/building accuracy."""
    token = await _get_mappls_token(client)
    headers = {"User-Agent": f"PVMaps/0.1 ({CONTACT})"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif MAPPLS_REST_KEY:
        # Some Mappls legacy plans use static REST key header/query
        headers["Authorization"] = f"Bearer {MAPPLS_REST_KEY}"
    else:
        return []

    hits: list[GeocodeHit] = []

    # 1. Try Mappls Autosuggest / Search
    try:
        r = await client.get(
            "https://atlas.mappls.com/api/places/search/json",
            params={"query": q},
            headers=headers,
            timeout=5.0,
        )
        if r.status_code == 200:
            data = r.json()
            locations = data.get("suggestedLocations") or []
            for item in locations[:limit]:
                lat = item.get("latitude")
                lon = item.get("longitude")
                if lat is not None and lon is not None:
                    addr = item.get("placeAddress") or ""
                    pname = item.get("placeName") or ""
                    display = f"{pname}, {addr}".strip(", ") if pname and pname not in addr else (addr or pname)
                    if display:
                        hits.append(
                            GeocodeHit(
                                display_name=display,
                                lat=float(lat),
                                lon=float(lon),
                                kind=item.get("type", "house"),
                                matched_query=None,
                            )
                        )
    except Exception:
        pass

    if hits:
        return hits

    # 2. Try Mappls Geocode endpoint as fallback
    try:
        r = await client.get(
            "https://atlas.mappls.com/api/places/geocode",
            params={"address": q},
            headers=headers,
            timeout=5.0,
        )
        if r.status_code == 200:
            data = r.json()
            cop_results = data.get("copResults") or []
            for item in cop_results[:limit]:
                lat = item.get("latitude")
                lon = item.get("longitude")
                if lat is not None and lon is not None:
                    addr = item.get("formattedAddress") or item.get("houseNumber")
                    if addr:
                        hits.append(
                            GeocodeHit(
                                display_name=str(addr),
                                lat=float(lat),
                                lon=float(lon),
                                kind="house",
                                matched_query=None,
                            )
                        )
    except Exception:
        pass

    return hits


async def _search(client: httpx.AsyncClient, q: str, limit: int) -> list[dict[str, Any]]:
    """Query Nominatim, with one retry on 429 after respecting Retry-After."""
    for _attempt in range(2):
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
        if r.status_code == 429:
            wait = float(r.headers.get("Retry-After", "2"))
            await asyncio.sleep(min(wait, 5.0))
            continue
        r.raise_for_status()
        payload = r.json()
        return list(payload) if isinstance(payload, list) else []
    # Both attempts got 429 — return empty rather than raising.
    return []


@router.get("/geocode", response_model=list[GeocodeHit])
async def geocode(
    q: str = Query(min_length=3, max_length=200),
    limit: int = Query(default=6, ge=1, le=10),
) -> list[GeocodeHit]:
    """Resolve a free-text address to coordinates.
    
    If MapmyIndia / Mappls credentials are configured, queries Mappls first for
    exact building/door-number level resolution in India.
    Otherwise (or if Mappls yields no results), falls back to Nominatim.
    """
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            # Check MapmyIndia / Mappls first if configured
            if (MAPPLS_CLIENT_ID and MAPPLS_CLIENT_SECRET) or MAPPLS_REST_KEY:
                mappls_hits = await _search_mappls(client, q, limit)
                if mappls_hits:
                    return mappls_hits

            # Fallback to Nominatim with variant broadening
            variants = _variants(q)
            for attempt, candidate in enumerate(variants):
                # Nominatim requires ≤1 req/s. Without this pause, rapid
                # variant attempts trigger 429s and the search returns nothing.
                if attempt > 0:
                    await asyncio.sleep(1.1)
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
