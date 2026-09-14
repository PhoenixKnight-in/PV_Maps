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


import math


class ScoreBreakdown(BaseModel):
    building_match: int = 0
    street_match: int = 0
    locality_match: int = 0
    pin_match: int = 0
    section_match: int = 0
    total_score: int = 0


class LocationResolveRequest(BaseModel):
    service_number: str | None = None
    meter_number: str | None = None
    address: str | None = None
    section: str | None = None
    circle: str | None = None
    user_lat: float | None = None
    user_lon: float | None = None


class LocationResolveResponse(BaseModel):
    latitude: float
    longitude: float
    accuracy_meters: float
    confidence: float
    source: str
    requires_user_confirmation: bool
    level: int
    display_name: str
    score_breakdown: ScoreBreakdown | None = None
    user_distance_meters: float | None = None
    user_distance_check: str | None = None
    details: str


class LocationConfirmRequest(BaseModel):
    service_number: str
    meter_number: str | None = None
    consumer_name: str | None = None
    section: str | None = None
    circle: str | None = None
    address: str | None = None
    latitude: float
    longitude: float
    accuracy_meters: float = 10.0
    source: str = "USER_CONFIRMED_GPS"


PILOT_CONNECTIONS: dict[str, dict[str, Any]] = {
    "08-211-019-1233": {
        "meter_number": "1773876",
        "consumer_name": "A.RAJAGOPAL",
        "section": "GANDHI NAGAR / EAST",
        "circle": "VELLORE",
        "address": "3rd East Cross Road, Gandhi Nagar, Katpadi, Vellore, Tamil Nadu",
        "latitude": 12.95390,
        "longitude": 79.14870,
        "accuracy_meters": 10.0,
        "source": "TNPDCL_GIS",
        "confidence": 0.98,
    }
}

CONFIRMED_CONNECTIONS: dict[str, dict[str, Any]] = {}


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(r * c, 1)


def compute_confidence_score(
    hit_display_name: str,
    hit_kind: str | None,
    raw_address: str,
    section: str | None,
    circle: str | None,
) -> tuple[int, ScoreBreakdown]:
    score = 0
    breakdown = ScoreBreakdown()
    lower_name = hit_display_name.lower()
    lower_addr = raw_address.lower()

    # 1. Exact building / apartment (+40)
    if hit_kind in ("building", "house", "apartment", "residential", "rooftop"):
        breakdown.building_match = 40
        score += 40

    # 2. Exact street found (+25)
    street_m = re.search(r"([0-9a-z\s]+(?:road|street|cross|lane|salai|ave|nagar))", lower_addr)
    if street_m:
        tokens = [t for t in street_m.group(1).split() if len(t) > 2]
        if any(tok in lower_name for tok in tokens):
            breakdown.street_match = 25
            score += 25

    # 3. Locality matches (+15)
    for loc in ("gandhi nagar", "katpadi", "vellore", "bharathi nagar", "viruthampattu"):
        if loc in lower_addr and loc in lower_name:
            breakdown.locality_match = 15
            score += 15
            break

    # 4. PIN matches (+10)
    pin_m = re.search(r"\b(6[0-9]{5})\b", raw_address)
    if pin_m and pin_m.group(1) in hit_display_name:
        breakdown.pin_match = 10
        score += 10

    # 5. TNPDCL section matches (+10)
    if section:
        sec_tokens = [t.strip().lower() for t in re.split(r"[/\\]", section) if len(t.strip()) > 3]
        if any(st in lower_name for st in sec_tokens):
            breakdown.section_match = 10
            score += 10

    breakdown.total_score = min(score, 100)
    return breakdown.total_score, breakdown


@router.post("/locate/resolve", response_model=LocationResolveResponse)
@router.post("/resolve-location", response_model=LocationResolveResponse)
async def resolve_location(req: LocationResolveRequest) -> LocationResolveResponse:
    norm_svc = re.sub(r"[\s-]", "", req.service_number or "")
    norm_meter = req.meter_number.strip() if req.meter_number else None

    # Level 1 & 2: Check Confirmed or Pilot TNPDCL GIS connections
    for pool, default_src, default_conf in [
        (CONFIRMED_CONNECTIONS, "USER_CONFIRMED_GPS", 1.0),
        (PILOT_CONNECTIONS, "TNPDCL_GIS", 0.98),
    ]:
        for key, rec in pool.items():
            k_clean = re.sub(r"[\s-]", "", key)
            m_clean = rec.get("meter_number")
            if (norm_svc and norm_svc == k_clean) or (norm_meter and m_clean and norm_meter == m_clean):
                lat = float(rec["latitude"])
                lon = float(rec["longitude"])
                dist = None
                dist_check = None
                if req.user_lat is not None and req.user_lon is not None:
                    dist = haversine_distance_meters(req.user_lat, req.user_lon, lat, lon)
                    dist_check = "likely" if dist <= 150 else ("suspicious" if dist > 500 else "moderate")

                return LocationResolveResponse(
                    latitude=lat,
                    longitude=lon,
                    accuracy_meters=float(rec.get("accuracy_meters", 10.0)),
                    confidence=float(rec.get("confidence", default_conf)),
                    source=str(rec.get("source", default_src)),
                    requires_user_confirmation=False,
                    level=1 if default_src == "TNPDCL_GIS" else 4,
                    display_name=str(rec.get("address") or f"EB Connection {req.service_number or key}"),
                    score_breakdown=ScoreBreakdown(
                        building_match=40, street_match=25, locality_match=15, pin_match=10, section_match=10, total_score=100
                    ),
                    user_distance_meters=dist,
                    user_distance_check=dist_check,
                    details=f"Authoritative record matched for Service No: {req.service_number or key}",
                )

    # Level 3: Fallback to Multi-Component Geocoding + Confidence Engine
    addr_query = req.address or f"{req.section or ''}, {req.circle or 'Vellore'}, Tamil Nadu"
    clean_query = _BUILDINGS_RE.sub("", addr_query)
    clean_query = _CAREOF_RE.sub("", clean_query)
    for suf in _GLUED:
        clean_query = re.sub(rf"(?i)\b([a-z]{{3,}}?){suf}\b", r"\1 " + suf, clean_query)
    clean_query = re.sub(r"\s+", " ", clean_query).strip(" ,")

    hits: list[GeocodeHit] = []
    async with httpx.AsyncClient(timeout=12.0) as client:
        # Try Mappls first if configured
        if (MAPPLS_CLIENT_ID and MAPPLS_CLIENT_SECRET) or MAPPLS_REST_KEY:
            hits = await _search_mappls(client, clean_query, limit=5)
        if not hits:
            # Fallback to Nominatim
            variants = _variants(clean_query)
            for attempt, cand in enumerate(variants):
                if attempt > 0:
                    await asyncio.sleep(1.1)
                res = await _search(client, cand, limit=3)
                if res:
                    hits = [
                        GeocodeHit(
                            display_name=str(h["display_name"]),
                            lat=float(h["lat"]),
                            lon=float(h["lon"]),
                            kind=h.get("type"),
                            matched_query=cand if attempt > 0 else None,
                        )
                        for h in res
                    ]
                    break

    if not hits:
        raise HTTPException(status_code=404, detail="Could not geocode address. Please pin your location on the map.")

    best_hit = hits[0]
    total_score, breakdown = compute_confidence_score(
        best_hit.display_name,
        best_hit.kind,
        req.address or "",
        req.section,
        req.circle,
    )
    confidence = round(total_score / 100.0, 2)
    # User requirement: Only accept automatically when confidence >= 85% (0.85).
    requires_confirmation = confidence < 0.85

    dist = None
    dist_check = None
    if req.user_lat is not None and req.user_lon is not None:
        dist = haversine_distance_meters(req.user_lat, req.user_lon, best_hit.lat, best_hit.lon)
        dist_check = "likely" if dist <= 150 else ("suspicious" if dist > 500 else "moderate")

    return LocationResolveResponse(
        latitude=best_hit.lat,
        longitude=best_hit.lon,
        accuracy_meters=30.0 if total_score >= 85 else 80.0,
        confidence=confidence,
        source="ADDRESS_GEOCODING",
        requires_user_confirmation=requires_confirmation,
        level=3,
        display_name=best_hit.display_name,
        score_breakdown=breakdown,
        user_distance_meters=dist,
        user_distance_check=dist_check,
        details="Multi-component address geocoding. User confirmation requested." if requires_confirmation else "High confidence geocoding match.",
    )


@router.post("/locate/confirm", response_model=LocationResolveResponse)
@router.post("/confirm-location", response_model=LocationResolveResponse)
async def confirm_location(req: LocationConfirmRequest) -> LocationResolveResponse:
    norm_svc = re.sub(r"[\s-]", "", req.service_number)
    CONFIRMED_CONNECTIONS[norm_svc] = {
        "service_number": req.service_number,
        "meter_number": req.meter_number,
        "consumer_name": req.consumer_name,
        "section": req.section,
        "circle": req.circle,
        "address": req.address,
        "latitude": req.latitude,
        "longitude": req.longitude,
        "accuracy_meters": req.accuracy_meters,
        "source": req.source,
        "confidence": 1.0,
    }

    return LocationResolveResponse(
        latitude=req.latitude,
        longitude=req.longitude,
        accuracy_meters=req.accuracy_meters,
        confidence=1.0,
        source=req.source,
        requires_user_confirmation=False,
        level=4,
        display_name=req.address or f"Confirmed location for EB connection {req.service_number}",
        score_breakdown=ScoreBreakdown(
            building_match=40, street_match=25, locality_match=15, pin_match=10, section_match=10, total_score=100
        ),
        details="User-confirmed coordinates saved and linked to Service Connection.",
    )


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
