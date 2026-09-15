"""Address resolution — the failure that puts a household on someone else's roof.

Measured 2026-09-15: asked for "3rd East Cross Road, Gandhi Nagar, Katpadi",
Nominatim answers "24th East Cross Road" -- a real street, 834 m away, in PIN
632006 instead of 632007 -- because OSM has no low-numbered East Cross Road in
Katpadi at all. Nothing in the response says a substitution happened, so the
only defence is the scorer, and the scorer was awarding a full street match on
the word "east".
"""

from __future__ import annotations

import math
import re

from pvmaps.api.routers.locate import (
    PILOT_CONNECTIONS,
    _ordinals,
    _reference_ring,
    _trilaterate,
    compute_confidence_score,
)

VELLORE = "3rd East Cross Road, Gandhi Nagar, Katpadi, Vellore, Tamil Nadu"
WRONG_STREET = (
    "Gandhi Nagar 24th East Cross Road, Bharathi Nagar, Viruthampattu, "
    "Brammapuram, Katpadi, Vellore, Tamil Nadu, 632006, India"
)
RIGHT_STREET = "3rd East Cross Road, Bharathi Nagar, Katpadi, Vellore, Tamil Nadu, 632007"


class _NoConnections:
    """A repository that holds no confirmed rooftops.

    The durable store is consulted before anything else, so these tests would
    otherwise depend on whatever a live database happened to contain.
    """

    async def get_confirmed_connection(self, service_hash, meter_hash):  # noqa: ANN001, ANN201
        return None

    async def save_confirmed_connection(self, service_hash, meter_hash, row):  # noqa: ANN001, ANN201
        return None


def test_a_different_numbered_road_is_not_a_street_match() -> None:
    """The regression that sent the pilot 834 m wrong."""
    _, breakdown = compute_confidence_score(WRONG_STREET, "tertiary", VELLORE, None, "VELLORE")
    assert breakdown.street_match == 0, (
        "24th East Cross Road scored as a match for 3rd East Cross Road; on a "
        "numbered grid the ordinal is the only part that identifies the street"
    )


def test_the_right_street_still_scores() -> None:
    """A guard that only ever says no is not a guard, it is an outage."""
    _, breakdown = compute_confidence_score(RIGHT_STREET, "street", VELLORE, None, "VELLORE")
    assert breakdown.street_match == 25


def test_wrong_street_cannot_reach_the_auto_accept_threshold() -> None:
    """resolve_location auto-accepts at >= 85 and then hides the pin prompt."""
    total, _ = compute_confidence_score(WRONG_STREET, "tertiary", VELLORE, None, "VELLORE")
    assert total < 85, f"wrong street would be auto-accepted at {total}"


def test_ordinals_are_normalised() -> None:
    assert _ordinals("3rd east cross road") == {"3"}
    assert _ordinals("gandhi nagar 24th east cross road") == {"24"}
    # A PIN code is not an ordinal.
    assert _ordinals("katpadi, vellore, 632007") == set()


def test_trilateration_recovers_a_known_point() -> None:
    """Mappls gives an eLoc and a distance, never a coordinate, on this plan."""
    truth = (12.959108, 79.143165)
    m_lat = 111_132.0
    m_lon = 111_320.0 * math.cos(math.radians(truth[0]))
    obs = [
        (la, lo, math.hypot((lo - truth[1]) * m_lon, (la - truth[0]) * m_lat))
        for la, lo in _reference_ring((12.9546, 79.1487))
    ]
    solved = _trilaterate(obs)
    assert solved is not None
    lat, lon, residual = solved
    off = math.hypot((lon - truth[1]) * m_lon, (lat - truth[0]) * m_lat)
    assert off < 1.0, f"recovered a point {off:.1f} m from truth"
    assert residual < 1.0


def test_trilateration_refuses_inconsistent_distances() -> None:
    """Distances that describe no single point must yield a large residual, so
    the caller discards them rather than inventing a location."""
    obs = [(12.95, 79.14, 100.0), (12.96, 79.15, 100.0), (12.94, 79.16, 100.0)]
    solved = _trilaterate(obs)
    assert solved is not None
    assert solved[2] > 25.0, "an impossible fix was reported as consistent"


def test_the_pilot_fixture_does_not_claim_an_authority_it_lacks() -> None:
    """It is a geocoded street, not a TNPDCL GIS extract, and it must say so --
    a record claiming 0.98 suppresses the confirm-your-roof prompt entirely."""
    rec = PILOT_CONNECTIONS["08-211-019-1233"]
    assert rec["source"] != "TNPDCL_GIS"
    assert rec["geocode_level"] == "street"
    assert rec["confidence"] < 0.85
    assert rec["accuracy_meters"] >= 100.0


def test_mappls_query_fits_the_undocumented_45_char_cap() -> None:
    """46 characters is a 400 with an empty body -- bisected 2026-09-15.

    The real address that exposed it is 48 characters, so this is not an edge
    case: it is the ordinary path.
    """
    from pvmaps.api.routers.locate import MAPPLS_QUERY_MAX_CHARS, _mappls_query

    for raw in (
        VELLORE,
        "3rd East Cross Road, Gandhi Nagar, Katpadi, Vellore, Tamil Nadu, India",
        "No. 14/2, Sunbreeze Apartments, 3rd East Cross Road, Bharathi Nagar, Katpadi",
    ):
        out = _mappls_query(raw)
        assert len(out) <= MAPPLS_QUERY_MAX_CHARS, f"{len(out)} chars: {out!r}"
        assert "," not in out
        # Whole words only -- a query cut mid-token matches nothing at all.
        source = re.sub(r"[^\w\s&./-]", " ", raw).split()
        for word in out.split():
            assert word in source, f"{word!r} was cut mid-token"


def test_the_street_survives_the_trim() -> None:
    """Indian addresses run specific -> general, so the identifying part is the
    head. Trimming must never cost the street name to save the state name."""
    from pvmaps.api.routers.locate import _mappls_query

    out = _mappls_query(VELLORE).lower()
    assert "3rd east cross road" in out


def test_an_unknown_service_number_is_a_miss_not_a_city_centroid() -> None:
    """A connection number is unique, but uniqueness only locates a household
    if you hold the registry mapping it to a service point. PV Maps has no
    TNPDCL feed, so an unknown number must say so.

    It used to fall through to Level 3 and build the query ", Vellore, Tamil
    Nadu" -- which geocodes fine, to the middle of Vellore, and came back
    carrying a confidence score.
    """
    import asyncio

    from fastapi import HTTPException

    from pvmaps.api.routers.locate import LocationResolveRequest, resolve_location

    req = LocationResolveRequest(service_number="99-999-999-9999")
    try:
        asyncio.run(resolve_location(req, _NoConnections()))
    except HTTPException as exc:
        assert exc.status_code == 404
        assert "TNPDCL" in exc.detail
    else:
        raise AssertionError("an unknown service number returned a location")


def test_a_known_service_number_still_resolves_without_an_address() -> None:
    """The registry lookup must not be collateral damage of the guard above."""
    import asyncio

    from pvmaps.api.routers.locate import LocationResolveRequest, resolve_location

    out = asyncio.run(
        resolve_location(
            LocationResolveRequest(service_number="08-211-019-1233"), _NoConnections()
        )
    )
    assert out.level == 1
    assert out.requires_user_confirmation is True
    assert abs(out.latitude - 12.959108) < 1e-4


def test_a_connection_number_is_never_stored_in_readable_form() -> None:
    """ARCHITECTURE.md 8: do not retain consumer numbers.

    The durable store is keyed by an HMAC so a confirmed rooftop survives a
    restart without the table becoming a list of who lives where.
    """
    from pvmaps.api import connection_id

    connection_id.CONNECTION_HASH_KEY = "test-key-not-a-real-secret"
    try:
        d = connection_id.digest("08-211-019-1233")
        assert d is not None and len(d) == 64
        assert "08" not in d or d != "08-211-019-1233"
        assert "1233" not in connection_id.digest("08-211-019-1233")

        # Punctuation is not identity: one connection, one digest.
        assert d == connection_id.digest("08 211 019 1233")
        assert d == connection_id.digest("082110191233")

        # A different connection is a different row.
        assert d != connection_id.digest("08-211-019-1234")

        # The key is load-bearing: without it, nothing is stored at all.
        connection_id.CONNECTION_HASH_KEY = ""
        assert connection_id.digest("08-211-019-1233") is None
        assert connection_id.persistence_enabled() is False
    finally:
        connection_id.CONNECTION_HASH_KEY = ""
