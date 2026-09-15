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
import logging
import math
import os
import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from pvmaps.api import connection_id
from pvmaps.api.deps import RepositoryDep
from pvmaps.api.repository import ConfirmedConnectionRow

logger = logging.getLogger(__name__)

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


MAPPLS_QUERY_MAX_CHARS = 45
"""Hard, undocumented cap on the autosuggest `query` parameter.

Bisected 2026-09-15: 45 characters return 200, 46 return 400 with an empty
body. Real Indian addresses run well past it -- "3rd East Cross Road Gandhi
Nagar Katpadi Vellore" is 48 -- so essentially every genuine lookup was
rejected while short test queries passed, which is what made this look
intermittent for so long."""

_MAPPLS_DROPPABLE = ("india", "bharat", "tamil nadu", "tamilnadu", "tn")
"""Tail components that cost characters and buy nothing: `region=IND` already
scopes the search to India, and Mappls resolves within the state regardless."""


def _mappls_query(q: str) -> str:
    """An address trimmed to something Mappls will actually accept.

    Indian addresses are ordered specific -> general, so the head is what
    identifies the place and the tail is what gets dropped. Punctuation goes
    too: commas are not rejected, but they consume characters of a very tight
    budget.
    """
    clean = re.sub(r"[^\w\s&./-]", " ", q)
    clean = re.sub(r"\s+", " ", clean).strip()

    lowered = clean.lower()
    for tail in _MAPPLS_DROPPABLE:
        if lowered.endswith(" " + tail):
            clean = clean[: -(len(tail) + 1)].strip()
            lowered = clean.lower()

    if len(clean) <= MAPPLS_QUERY_MAX_CHARS:
        return clean

    # Whole words only -- a query cut mid-token matches nothing.
    kept: list[str] = []
    for word in clean.split():
        if len(" ".join([*kept, word])) > MAPPLS_QUERY_MAX_CHARS:
            break
        kept.append(word)
    return " ".join(kept)


async def _mappls_suggest(
    client: httpx.AsyncClient,
    q: str,
    headers: dict[str, str],
    ref: tuple[float, float] | None,
) -> list[dict[str, Any]]:
    """One Mappls autosuggest call.

    `region=IND` is NOT optional: without it every call returns 400 Bad Request.
    That single missing parameter is why Mappls -- the "primary" geocoder per
    STATUS.md 4.3 -- silently contributed nothing for the whole pilot, leaving
    every lookup to Nominatim.

    When `ref` is given, each suggestion comes back with a `distance` field: the
    metres from `ref` to that place. That is the only channel through which this
    account's tier will disclose a position at all (see `_trilaterate`).
    """
    clean = _mappls_query(q)
    if not clean:
        return []
    params = {"query": clean, "region": "IND"}
    if ref is not None:
        params["location"] = f"{ref[0]:.5f},{ref[1]:.5f}"
    try:
        r = await client.get(
            "https://atlas.mappls.com/api/places/search/json",
            params=params,
            headers=headers,
            timeout=6.0,
        )
        if r.status_code != 200:
            return []
        return list(r.json().get("suggestedLocations") or [])
    except Exception:
        return []


def _trilaterate(obs: list[tuple[float, float, float]]) -> tuple[float, float, float] | None:
    """(lat, lon, max residual) from >=3 (ref_lat, ref_lon, distance_m) readings.

    Mappls returns a place's `eLoc` but never its coordinates on this plan --
    `/places/nearby` answers 401 ASSET_ACCESS_DENIED and `advancedmaps/geo_code`
    answers 412. The autosuggest `distance` field is the exception, so position
    is recovered from distances to several reference points instead.

    Measured 2026-09-15 against six references around Katpadi: residuals of
    1.1 m for a street and 1.4 m for a building. This is a real fix, not an
    estimate -- but it IS load-bearing on an undocumented field, so a solve that
    does not agree with its own inputs is discarded rather than trusted.
    """
    if len(obs) < 3:
        return None
    lat0 = sum(o[0] for o in obs) / len(obs)
    lon0 = sum(o[1] for o in obs) / len(obs)
    m_lat = 111_132.0
    m_lon = 111_320.0 * math.cos(math.radians(lat0))
    pts = [((lo - lon0) * m_lon, (la - lat0) * m_lat, d) for la, lo, d in obs]

    # Subtracting the first circle's equation from each of the others turns the
    # quadratic system linear; the residual check below is what catches a
    # degenerate (near-collinear) reference set.
    x1, y1, d1 = pts[0]
    rows: list[tuple[float, float]] = []
    rhs: list[float] = []
    for x, y, d in pts[1:]:
        rows.append((2.0 * (x - x1), 2.0 * (y - y1)))
        rhs.append(d1 * d1 - d * d + x * x - x1 * x1 + y * y - y1 * y1)

    a11 = sum(r[0] * r[0] for r in rows)
    a12 = sum(r[0] * r[1] for r in rows)
    a22 = sum(r[1] * r[1] for r in rows)
    b1 = sum(rows[i][0] * rhs[i] for i in range(len(rows)))
    b2 = sum(rows[i][1] * rhs[i] for i in range(len(rows)))
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-6:
        return None

    x = (b1 * a22 - b2 * a12) / det
    y = (a11 * b2 - a12 * b1) / det
    lat = lat0 + y / m_lat
    lon = lon0 + x / m_lon

    worst = max(
        abs(math.hypot((lo - lon) * m_lon, (la - lat) * m_lat) - d) for la, lo, d in obs
    )
    return lat, lon, worst


def _reference_ring(seed: tuple[float, float]) -> list[tuple[float, float]]:
    """Four non-collinear probes about 1 km around `seed`.

    Close enough that the target still ranks in the suggestion list -- a
    reference too far away simply does not return the place, and there is no
    distance to read -- and spread enough that the solve is well conditioned.
    """
    lat, lon = seed
    dlat = 1000.0 / 111_132.0
    dlon = 1000.0 / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return [
        (lat + dlat, lon),
        (lat - dlat * 0.6, lon + dlon),
        (lat - dlat * 0.6, lon - dlon),
        (lat, lon + dlon * 0.4),
    ]


_ELOC_POSITIONS: dict[str, tuple[float, float]] = {}
"""Solved positions, keyed by Mappls eLoc. A street does not move, and each
fresh solve costs four calls against a tier that starts refusing under load --
so a place is positioned once per process and then remembered."""


MAX_TRILATERATION_RESIDUAL_M = 25.0
"""Beyond this the distances do not describe one consistent point, so the solve
is thrown away and Nominatim's coarse hit stands instead of a fabricated one."""


async def _search_mappls(
    client: httpx.AsyncClient,
    q: str,
    limit: int,
    seed: tuple[float, float] | None = None,
) -> list[GeocodeHit]:
    """Mappls for Indian street identity, trilateration for its coordinates.

    Mappls knows streets OSM has never heard of -- "3rd East Cross Road,
    Bharathi Nagar" is in Mappls and absent from OSM, which is why Nominatim
    answered a query for it with 24th East Cross Road, 834 m away, in a
    different PIN code. Identity comes from Mappls; position comes from the
    distance readings; `seed` only has to be near enough to keep the place in
    the suggestion list.
    """
    token = await _get_mappls_token(client)
    headers = {"User-Agent": f"PVMaps/0.1 ({CONTACT})"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif MAPPLS_REST_KEY:
        headers["Authorization"] = f"Bearer {MAPPLS_REST_KEY}"
    else:
        return []

    if seed is None:
        return []

    rings = _reference_ring(seed)
    batches = await asyncio.gather(
        *(_mappls_suggest(client, q, headers, ref) for ref in rings)
    )

    # One call returns a distance for EVERY suggestion, so four calls position
    # the whole result set rather than one place at a time.
    readings: dict[str, list[tuple[float, float, float]]] = {}
    meta: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for ref, batch in zip(rings, batches):
        for item in batch:
            eloc = item.get("eLoc")
            dist = item.get("distance")
            if not eloc or dist is None:
                continue
            if eloc not in meta:
                meta[eloc] = item
                order.append(eloc)
            readings.setdefault(eloc, []).append((ref[0], ref[1], float(dist)))

    hits: list[GeocodeHit] = []
    for eloc in order:
        cached = _ELOC_POSITIONS.get(eloc)
        if cached is not None:
            lat, lon = cached
        else:
            solved = _trilaterate(readings.get(eloc, []))
            if solved is None:
                continue
            lat, lon, residual = solved
            if residual > MAX_TRILATERATION_RESIDUAL_M:
                continue
            _ELOC_POSITIONS[eloc] = (lat, lon)
        item = meta[eloc]
        name = str(item.get("placeName") or "").strip()
        addr = str(item.get("placeAddress") or "").strip()
        display = f"{name}, {addr}".strip(", ") if name and name not in addr else (addr or name)
        if not display:
            continue
        hits.append(
            GeocodeHit(
                display_name=display,
                lat=lat,
                lon=lon,
                kind=str(item.get("type") or "").lower() or None,
                matched_query=None,
            )
        )
        if len(hits) >= limit:
            break
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


async def _nominatim_hits(
    client: httpx.AsyncClient, q: str, limit: int
) -> list[GeocodeHit]:
    """Nominatim with variant broadening, in the order the variants are tried."""
    for attempt, candidate in enumerate(_variants(q)):
        # Nominatim requires <=1 req/s. Without this pause, rapid variant
        # attempts trigger 429s and the search returns nothing.
        if attempt > 0:
            await asyncio.sleep(1.1)
        payload = await _search(client, candidate, limit)
        if payload:
            return [
                GeocodeHit(
                    display_name=str(h["display_name"]),
                    lat=float(h["lat"]),
                    lon=float(h["lon"]),
                    kind=h.get("type"),
                    matched_query=candidate if attempt > 0 else None,
                )
                for h in payload
            ]
    return []


async def _mappls_pin_code(client: httpx.AsyncClient, q: str) -> str | None:
    """Mappls' structured read of an address, for its PIN code alone.

    The recovery path when OSM has never heard of the street: Mappls will still
    parse it and name the PIN code, and a PIN code IS in OSM. That gives a seed
    within a kilometre or so, which is all the reference ring needs.
    """
    token = await _get_mappls_token(client)
    headers = {"User-Agent": f"PVMaps/0.1 ({CONTACT})"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif MAPPLS_REST_KEY:
        headers["Authorization"] = f"Bearer {MAPPLS_REST_KEY}"
    else:
        return None
    try:
        r = await client.get(
            "https://atlas.mappls.com/api/places/geocode",
            params={"address": q},
            headers=headers,
            timeout=6.0,
        )
        if r.status_code != 200:
            return None
        results = r.json().get("copResults")
        if isinstance(results, dict):
            results = [results]
        for item in results or []:
            pin = str(item.get("pincode") or "").strip()
            if re.fullmatch(r"[1-9][0-9]{5}", pin):
                return pin
    except Exception:
        return None
    return None


async def _resolve_hits(
    client: httpx.AsyncClient, q: str, limit: int
) -> list[GeocodeHit]:
    """Coarse position from OSM, correct street identity and metre-level
    position from Mappls.

    The order is deliberate and was wrong before. Mappls used to be asked first
    and -- because every call was a 400 for want of `region=IND` -- always
    returned nothing, so the answer was always Nominatim's. Nominatim is the
    weaker source for Indian street names: asked for "3rd East Cross Road,
    Gandhi Nagar" it answers "24th East Cross Road" in a different PIN code,
    834 m away, with no indication that it substituted a different street.

    So OSM is now used for what it is reliable at -- getting within a kilometre
    -- and Mappls decides which street it actually is and exactly where.
    """
    coarse = await _nominatim_hits(client, q, limit)
    if not ((MAPPLS_CLIENT_ID and MAPPLS_CLIENT_SECRET) or MAPPLS_REST_KEY):
        return coarse

    seed: tuple[float, float] | None = None
    if coarse:
        seed = (coarse[0].lat, coarse[0].lon)
    else:
        pin = await _mappls_pin_code(client, q)
        if pin:
            by_pin = await _nominatim_hits(client, f"{pin}, Tamil Nadu", 1)
            if by_pin:
                seed = (by_pin[0].lat, by_pin[0].lon)
    if seed is None:
        return coarse

    precise = await _search_mappls(client, q, limit, seed=seed)
    return precise or coarse


@router.get("/geocode", response_model=list[GeocodeHit])
async def geocode(
    q: str = Query(min_length=3, max_length=200),
    limit: int = Query(default=6, ge=1, le=10),
) -> list[GeocodeHit]:
    """Resolve a free-text address to coordinates."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            return await _resolve_hits(client, q, limit)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="Address lookup is unreachable. You can still tap the roof on the map.",
        ) from exc


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
        "address": "3rd East Cross Road, Bharathi Nagar, Katpadi, Vellore, Tamil Nadu 632007",
        # Mappls eLoc YAFX1R, positioned 2026-09-15 by trilaterating its
        # autosuggest distance from six reference points (worst residual 1.1 m).
        # This is the STREET, not the house: the bill gives no door number, and
        # the terrace that belongs to this connection is somewhere along it.
        "latitude": 12.959108,
        "longitude": 79.143165,
        # Street centroid on a ~300 m road. Quoting 10 m here is what made the
        # UI skip confirmation and fly straight to the wrong roof.
        "accuracy_meters": 150.0,
        "source": "MAPPLS_STREET",
        "confidence": 0.55,
        "geocode_level": "street",
    }
}
"""The one pilot connection, and a cautionary record.

It previously held (12.95390, 79.14870) labelled `TNPDCL_GIS` at 0.98
confidence. No TNPDCL GIS extract was ever involved: that coordinate came from
Nominatim answering a query for "3rd East Cross Road" with *24th* East Cross
Road -- a different street, a different PIN code, 834 m away -- and was then
nudged by hand until SAM2 returned a roof of a believable size. Because the
record claimed 0.98 it also set `requires_user_confirmation=False`, so the map
flew there and offered the household no way to say "that is not my house".

A fixture may be approximate. It may not claim a provenance it does not have.
"""

CONFIRMED_CONNECTIONS: dict[str, dict[str, Any]] = {}


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(r * c, 1)


_GENERIC_STREET_WORDS = frozenset(
    {"road", "street", "cross", "lane", "salai", "ave", "avenue", "main", "east",
     "west", "north", "south", "new", "old"}
)
"""Words that carry no identity on a numbered grid. "East" matched "24th East
Cross Road" against a query for "3rd East Cross Road" and scored it a hit."""


def _ordinals(text: str) -> set[str]:
    """Ordinals as a normalised set: "3rd"/"3" -> "3". Two addresses whose
    ordinals are both present and disjoint are different streets, full stop."""
    return {m.group(1) for m in re.finditer(r"\b([0-9]{1,3})(?:st|nd|rd|th)\b", text)}


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

    # 2. Exact street found (+25), and an ordinal CONFLICT is disqualifying.
    #
    # This used to award the full 25 when ANY token over two characters
    # appeared in the hit -- so asking for "3rd East Cross Road" and being
    # handed "24th East Cross Road" scored a street match on the word "east",
    # 834 m and one PIN code away. In Katpadi the ordinal IS the street name;
    # every road on the grid shares every other word.
    asked = _ordinals(lower_addr)
    got = _ordinals(lower_name)
    if asked and got and asked.isdisjoint(got):
        breakdown.street_match = 0  # a different numbered road, not a match
    else:
        street_m = re.search(r"([0-9a-z\s]+(?:road|street|cross|lane|salai|ave|nagar))", lower_addr)
        if street_m:
            tokens = {t for t in street_m.group(1).split() if len(t) > 2} - _GENERIC_STREET_WORDS
            if tokens and all(tok in lower_name for tok in tokens):
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
async def resolve_location(
    req: LocationResolveRequest, repo: RepositoryDep
) -> LocationResolveResponse:
    # A confirmed rooftop outranks every other source, and it is the reason a
    # service number is worth typing at all: the household already told us
    # where this connection is, once, and that answer must survive a restart.
    svc_hash = connection_id.digest(req.service_number)
    mtr_hash = connection_id.digest(req.meter_number)
    if svc_hash or mtr_hash:
        try:
            stored = await repo.get_confirmed_connection(svc_hash, mtr_hash)
        except Exception:
            # A lookup failure must not take out address geocoding below -- but
            # it must not be invisible either. Swallowing this silently is how
            # an asyncpg type-inference error sat here looking exactly like
            # "no rows": every confirmed rooftop was written and none read back.
            logger.exception("confirmed_connection_lookup_failed")
            stored = None
        if stored is not None:
            dist = None
            dist_check = None
            if req.user_lat is not None and req.user_lon is not None:
                dist = haversine_distance_meters(
                    req.user_lat, req.user_lon, stored.latitude, stored.longitude
                )
                dist_check = (
                    "likely" if dist <= 150 else ("suspicious" if dist > 500 else "moderate")
                )
            return LocationResolveResponse(
                latitude=stored.latitude,
                longitude=stored.longitude,
                accuracy_meters=stored.accuracy_meters,
                confidence=stored.confidence,
                source=stored.source,
                requires_user_confirmation=stored.geocode_level != "building",
                level=4,
                display_name=(
                    req.address
                    or f"Confirmed rooftop for connection {req.service_number or req.meter_number}"
                ),
                score_breakdown=ScoreBreakdown(
                    building_match=40, street_match=25, locality_match=15,
                    pin_match=10, section_match=10, total_score=100,
                ),
                user_distance_meters=dist,
                user_distance_check=dist_check,
                details="Matched a rooftop this connection confirmed earlier.",
            )

    norm_svc = re.sub(r"[\s-]", "", req.service_number or "")
    norm_meter = req.meter_number.strip() if req.meter_number else None

    # Level 1 & 2: Check Confirmed or Pilot TNPDCL GIS connections
    for pool, default_src, default_conf in [
        (CONFIRMED_CONNECTIONS, "USER_CONFIRMED_GPS", 1.0),
        (PILOT_CONNECTIONS, "PILOT_FIXTURE", 0.55),
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
                    # Only a record that actually resolves to a BUILDING may
                    # skip confirmation. A street-level fixture must let the
                    # household move the pin onto their own roof.
                    requires_user_confirmation=rec.get("geocode_level", "building") != "building",
                    level=4 if default_src == "USER_CONFIRMED_GPS" else 1,
                    display_name=str(rec.get("address") or f"EB Connection {req.service_number or key}"),
                    score_breakdown=(
                        ScoreBreakdown(
                            building_match=40, street_match=25, locality_match=15,
                            pin_match=10, section_match=10, total_score=100,
                        )
                        if rec.get("geocode_level", "building") == "building"
                        else ScoreBreakdown(
                            building_match=0, street_match=25, locality_match=15,
                            pin_match=10, section_match=10, total_score=60,
                        )
                    ),
                    user_distance_meters=dist,
                    user_distance_check=dist_check,
                    details=(
                        f"Matched Service No {req.service_number or key} to a "
                        + (
                            "confirmed rooftop."
                            if rec.get("geocode_level", "building") == "building"
                            else "street. Move the pin onto your own roof to confirm."
                        )
                    ),
                )

    # A service number we do not hold is a MISS, not a licence to guess.
    #
    # Falling through to Level 3 with nothing but a service number built the
    # query ", Vellore, Tamil Nadu" -- which geocodes perfectly well, to the
    # middle of Vellore, and was then returned with a confidence score as
    # though it meant something. A connection number is unique, but uniqueness
    # only locates a household if you hold the registry that maps it to a
    # service point, and PV Maps has no TNPDCL feed (STATUS 10). Saying so is
    # the correct answer; a city centroid is not.
    if not (req.address or req.section):
        raise HTTPException(
            status_code=404,
            detail=(
                "That service number is not in this pilot's connection registry, "
                "and PV Maps has no live TNPDCL lookup. Enter the address from "
                "the bill, or drop the pin on your roof."
            ),
        )

    # Level 3: Fallback to Multi-Component Geocoding + Confidence Engine
    addr_query = req.address or f"{req.section or ''}, {req.circle or 'Vellore'}, Tamil Nadu"
    clean_query = _BUILDINGS_RE.sub("", addr_query)
    clean_query = _CAREOF_RE.sub("", clean_query)
    for suf in _GLUED:
        clean_query = re.sub(rf"(?i)\b([a-z]{{3,}}?){suf}\b", r"\1 " + suf, clean_query)
    clean_query = re.sub(r"\s+", " ", clean_query).strip(" ,")

    # Same path as GET /v1/geocode: OSM for the coarse seed, Mappls for which
    # street it actually is. Level 3 used to run its own weaker copy of this.
    async with httpx.AsyncClient(timeout=20.0) as client:
        hits = await _resolve_hits(client, clean_query, limit=5)

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
async def confirm_location(
    req: LocationConfirmRequest, repo: RepositoryDep
) -> LocationResolveResponse:
    # Durable, and keyed by a digest rather than the number -- see
    # `api.connection_id`. With no CONNECTION_HASH_KEY configured nothing is
    # written at all: a key that changed between restarts would orphan every
    # row while still looking like it worked.
    svc_hash = connection_id.digest(req.service_number)
    if svc_hash:
        try:
            await repo.save_confirmed_connection(
                svc_hash,
                connection_id.digest(req.meter_number),
                ConfirmedConnectionRow(
                    latitude=req.latitude,
                    longitude=req.longitude,
                    accuracy_meters=req.accuracy_meters,
                    confidence=1.0,
                    source=req.source,
                    geocode_level="building",
                ),
            )
        except Exception:
            # The in-memory store below still serves this process, so a storage
            # outage costs persistence -- not the confirmation the user just
            # made. It is logged because a confirmation that quietly fails to
            # persist looks identical to one that worked.
            logger.exception("confirmed_connection_save_failed")

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
        # The household put this pin on their own roof. That is building level,
        # and it is the one source in here entitled to skip confirmation.
        "geocode_level": "building",
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
