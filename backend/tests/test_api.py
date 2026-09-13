"""API tests — ARCHITECTURE.md 5.2's surface, and the promises it makes.

These run against the real routers, the real serialisers, the real optimiser and
the real rule packs. Only the row fetch is faked (tests/fakes.py), because the
request path is supposed to be a row read plus arithmetic — if a test needs a
database to check a recommendation, the architecture has drifted.

The tests worth reading first are the ones that check a promise rather than a
shape:

    test_recommendation_never_exceeds_either_ceiling   PRD 10 acceptance
    test_every_result_carries_the_feasibility_disclosure
    test_persisted_run_carries_no_identifying_field    ARCHITECTURE.md 8
    test_usable_area_override_cannot_exceed_the_roof
    test_a_write_failure_does_not_cost_the_user_their_result
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from itertools import pairwise
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import ProgrammingError

from pvmaps.api.deps import get_repository
from pvmaps.api.main import create_app
from pvmaps.api.repository import YieldRow
from pvmaps.api.schemas import GRID_DISCLOSURE
from pvmaps.api.settings import Settings, load_settings
from tests.fakes import FakeRepository, FakeSessionFactory, building

ORIGIN = "http://localhost:5173"


def settings(**kw: Any) -> Settings:
    base = {
        "database_url": None,
        "cors_allow_origins": [ORIGIN],
        "log_level": "warning",
    }
    return Settings(**{**base, **kw})  # type: ignore[arg-type]


def make_app(repo: FakeRepository | None = None, **kw: Any) -> tuple[FastAPI, FakeRepository]:
    repo = repo or FakeRepository()
    app = create_app(settings(**kw))

    async def _repo() -> AsyncIterator[FakeRepository]:
        yield repo

    app.dependency_overrides[get_repository] = _repo
    return app, repo


def client(app: FastAPI) -> httpx.AsyncClient:
    # ASGITransport does not run lifespan, which suits these tests: lifespan's
    # only job is the connection pool, and there is no database here.
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


PROFILE = {
    "building_id": "bldg-demo-1",
    "monthly_units_kwh": 565,
    "sanctioned_load_kw": 3,
    "occupancy": "PARTIAL",
    "modifiers": [],
}


@pytest.fixture
async def api() -> AsyncIterator[tuple[httpx.AsyncClient, FakeRepository]]:
    app, repo = make_app()
    async with client(app) as c:
        yield c, repo


# ---------------------------------------------------------------------------
# Surface
# ---------------------------------------------------------------------------


async def test_phase_1_surface_is_exactly_what_the_architecture_lists() -> None:
    """ARCHITECTURE.md 5.2. An endpoint that is not on this list is scope creep,
    and the list is short on purpose."""
    app, _ = make_app()
    paths = set(app.openapi()["paths"])
    assert paths == {
        "/healthz",
        "/v1/search",
        "/v1/buildings/{building_id}",
        "/v1/sizing-runs",
        "/v1/bill-extract",
        "/v1/tariffs/current",
    }


async def test_no_grid_transformer_or_quota_endpoint_exists() -> None:
    """ARCHITECTURE.md 5.2: "The Phase 1 API has no transformer, quota,
    allocation, or grid-eligibility endpoint."

    The Phase 2 allocator is built and tested and sitting in the tree. This is
    the test that keeps it unreachable.
    """
    app, _ = make_app()
    spec = str(app.openapi()).lower()
    for forbidden in ("transformer", "quota", "allocat", "dtr", "feeder", "grid-passport"):
        assert forbidden not in spec, f"Phase 1 API mentions {forbidden!r}"


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


async def test_healthz_is_degraded_without_a_database(api: tuple[httpx.AsyncClient, Any]) -> None:
    """The browser uses this to decide whether to fall back to bundled pilot
    data (ARCHITECTURE.md 9.3). 200 here would strand it on requests that
    cannot succeed."""
    c, _ = api
    r = await c.get("/healthz")
    assert r.status_code == 503
    assert r.json()["database"] == "not_configured"
    assert r.json()["status"] == "degraded"


async def test_healthz_is_ok_when_the_database_answers() -> None:
    app, _ = make_app()
    app.state.session_factory = FakeSessionFactory()
    async with client(app) as c:
        r = await c.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["phase"] == 1


async def test_healthz_reports_an_unreachable_database_rather_than_crashing() -> None:
    app, _ = make_app()
    app.state.session_factory = FakeSessionFactory(fail=True)
    async with client(app) as c:
        r = await c.get("/healthz")
    assert r.status_code == 503
    assert r.json()["database"] == "unreachable"


async def test_healthz_is_degraded_when_the_migrations_have_not_run() -> None:
    """A reachable database with no tables answers `SELECT 1` perfectly well. The
    browser would then keep asking for roofs that cannot be read, instead of
    falling back to its bundle (ARCHITECTURE.md 9.3) -- so the probe counts roofs,
    and the state is named after its fix."""
    app, _ = make_app()
    app.state.session_factory = FakeSessionFactory(
        raises=ProgrammingError("SELECT count(*) FROM buildings", {}, Exception("no such table"))
    )
    async with client(app) as c:
        r = await c.get("/healthz")
    assert r.status_code == 503
    assert r.json()["database"] == "schema_missing"


async def test_healthz_is_degraded_when_the_seeder_has_not_run() -> None:
    """Migrated and empty. Every roof lookup would 404 through a perfectly healthy
    API, which is the hardest version of this failure to diagnose on stage."""
    app, _ = make_app()
    app.state.session_factory = FakeSessionFactory(pilot_roofs=0)
    async with client(app) as c:
        r = await c.get("/healthz")
    assert r.status_code == 503
    assert r.json()["database"] == "no_pilot_data"


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


async def test_search_returns_pilot_addresses(api: tuple[httpx.AsyncClient, Any]) -> None:
    c, _ = api
    r = await c.get("/v1/search", params={"q": "Katpadi"})
    assert r.status_code == 200
    [hit] = r.json()
    assert hit["building_id"] == "bldg-demo-1"
    assert hit["lat"] == pytest.approx(12.9202)
    assert set(hit) == {"id", "display_name", "building_id", "lat", "lon"}


async def test_search_applies_the_configured_limit(api: tuple[httpx.AsyncClient, Any]) -> None:
    c, repo = api
    await c.get("/v1/search", params={"q": "Katpadi"})
    assert repo.search_calls == [("Katpadi", 10)]


async def test_search_rejects_a_query_too_short_to_mean_anything(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    c, _ = api
    assert (await c.get("/v1/search", params={"q": "a"})).status_code == 422


async def test_search_for_an_unknown_address_is_empty_not_an_error(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    c, _ = api
    r = await c.get("/v1/search", params={"q": "Chennai"})
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Buildings
# ---------------------------------------------------------------------------


async def test_unknown_building_is_404_not_a_default_roof(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    c, _ = api
    assert (await c.get("/v1/buildings/nope")).status_code == 404


async def test_building_reports_the_conservative_roof_maximum(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """84 m2 usable, 9-12 m2/kWp: the cap is 84/12 = 7.0 kWp, and the band's
    optimistic end is reported separately rather than used."""
    c, _ = api
    b = (await c.get("/v1/buildings/bldg-demo-1")).json()
    assert b["usable_area_m2"] == 84.0
    assert b["roof_max_kwp"] == pytest.approx(7.0)
    assert b["roof_max_kwp_band"]["lo"] == pytest.approx(7.0)
    assert b["roof_max_kwp_band"]["hi"] == pytest.approx(9.33, abs=0.01)
    assert b["roof_max_kwp"] <= b["roof_max_kwp_band"]["hi"]


async def test_an_unanalysed_roof_says_so_rather_than_borrowing_authority(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """NFR-2. The regional band is published; applying it to *this* roof is an
    inference, and the payload has to say which it is."""
    c, _ = api
    b = (await c.get("/v1/buildings/bldg-demo-1")).json()
    assert b["yield_source"] == "REGIONAL_FALLBACK"
    assert b["analysis_version"] is None
    est = b["annual_yield_kwh_per_kwp"]
    assert est["source"] == "inferred"
    assert est["lo"] < est["value"] < est["hi"]
    assert est["confidence"] < 1.0


async def test_an_analysed_roof_reports_its_own_pvlib_band() -> None:
    analysed = building(
        analysis=YieldRow(
            version="pvlib-2026.1", value=1545.0, lo=1480.0, hi=1610.0,
            source="inferred", confidence=0.74,
        )
    )
    app, _ = make_app(FakeRepository({"bldg-demo-1": analysed}))
    async with client(app) as c:
        b = (await c.get("/v1/buildings/bldg-demo-1")).json()
    assert b["yield_source"] == "BUILDING"
    assert b["analysis_version"] == "pvlib-2026.1"
    assert b["annual_yield_kwh_per_kwp"]["lo"] == 1480.0
    assert b["annual_yield_kwh_per_kwp"]["confidence"] == 0.74


# ---------------------------------------------------------------------------
# Sizing — the product
# ---------------------------------------------------------------------------


async def test_recommendation_never_exceeds_either_ceiling(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """PRD 10 acceptance: "Recommended kWp never exceeds roof maximum or
    sanctioned-load maximum." Checked at the API boundary, which is where a
    number actually reaches a household."""
    c, _ = api
    r = (await c.post("/v1/sizing-runs", json=PROFILE)).json()
    assert r["recommended"]["kwp"] <= r["roof_max_kwp"]
    assert r["recommended"]["kwp"] <= r["sanctioned_load_max_kwp"]
    assert r["recommended"]["kwp"] <= r["feasible_max_kwp"]
    for candidate in r["curve"]:
        assert candidate["kwp"] <= r["feasible_max_kwp"]


async def test_the_contract_is_the_binding_constraint_not_the_roof(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """PRD 11 beat 1. 118 m2 of roof, 3 kW of sanctioned load."""
    c, _ = api
    r = (await c.post("/v1/sizing-runs", json=PROFILE)).json()
    assert r["roof_max_kwp"] == pytest.approx(7.0)
    assert r["sanctioned_load_max_kwp"] == 3.0
    assert r["binding_constraint"] == "SANCTIONED_LOAD"


async def test_recommendation_can_sit_below_what_is_allowed(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """The product's actual claim: the roof is not the recommendation."""
    c, _ = api
    r = (await c.post("/v1/sizing-runs", json=PROFILE)).json()
    assert r["is_economically_capped"] is True
    assert r["recommended"]["kwp"] < r["feasible_max_kwp"]


async def test_self_consumed_and_exported_stay_separate_numbers(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """FR-4.2 and FR-4.3. Never one blended 'savings' figure."""
    c, _ = api
    r = (await c.post("/v1/sizing-runs", json=PROFILE)).json()
    rec = r["recommended"]
    for key in (
        "self_consumed_kwh",
        "exported_kwh",
        "annual_self_consumed_kwh",
        "annual_exported_kwh",
        "annual_bill_savings",
        "annual_export_credit",
    ):
        assert key in rec, key
    assert rec["annual_self_consumed_kwh"]["lo"] == pytest.approx(
        rec["self_consumed_kwh"]["lo"] * 12
    )


async def test_export_is_not_valued_while_the_rate_band_is_pinned_at_zero(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """The deliberate zero in the assumptions pack. Valuing export at the retail
    slab rate is the overclaim this codebase exists to avoid, so the API must not
    quietly produce a non-zero credit."""
    c, _ = api
    r = (await c.post("/v1/sizing-runs", json=PROFILE)).json()
    for candidate in r["curve"]:
        assert candidate["annual_export_credit"] == {"lo": 0.0, "hi": 0.0}


async def test_a_larger_system_earns_less_per_kwh_generated(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """The curve is the argument (ARCHITECTURE.md 7f): once a system outgrows the
    daytime load, additional output is exported and the realised rate falls. A
    flat effective rate would mean an average-tariff shortcut had crept in."""
    c, _ = api
    curve = (await c.post("/v1/sizing-runs", json=PROFILE)).json()["curve"]
    assert len(curve) >= 3
    rates = [cand["effective_rate"]["hi"] for cand in curve]
    assert rates[-1] < rates[0]
    assert all(a >= b - 1e-9 for a, b in pairwise(rates))


async def test_every_result_carries_the_feasibility_disclosure(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """PRD 5.2 and 10. No Phase 1 result leaves the API without it, whatever the
    verdict."""
    c, _ = api
    for units in (95, 565, 1200):
        r = (await c.post("/v1/sizing-runs", json={**PROFILE, "monthly_units_kwh": units})).json()
        assert r["grid_feasibility"] == "NOT_VERIFIED"
        assert r["grid_disclosure"] == GRID_DISCLOSURE
        assert "TNPDCL" in r["grid_disclosure"]


async def test_results_are_flagged_provisional_while_rule_packs_are_unverified(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """The rule packs all read UNVERIFIED_AGAINST_PRIMARY_SOURCE, so this must be
    False and the UI must show its provisional banner. If someone marks a pack
    verified without reading the order, this test is not what catches it —
    test_tariff_golden.py is — but the flag has to travel."""
    c, _ = api
    r = (await c.post("/v1/sizing-runs", json=PROFILE)).json()
    assert r["assumptions_verified"] is False
    assert r["tariff_version"] == "tn-domestic-2025-07-01"
    assert r["subsidy_version"]
    assert r["assumptions_version"]


async def test_a_free_slab_household_gets_the_honest_zero(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """PRD G2 and demo beat 2. 95 units/month sits inside the free slab, so there
    is nothing for solar to displace and the API says so rather than finding a
    number."""
    c, _ = api
    r = (await c.post("/v1/sizing-runs", json={**PROFILE, "monthly_units_kwh": 95})).json()
    assert r["verdict"] == "NOT_ECONOMIC"
    assert r["recommended"] is None
    assert r["curve"], "the curve is still returned -- the user sees why, not just that"
    for candidate in r["curve"]:
        assert candidate["annual_bill_savings"]["hi"] == 0.0


async def test_sanctioned_load_is_never_defaulted(api: tuple[httpx.AsyncClient, Any]) -> None:
    """PRD 1.1 constraint #2. Guessing it fabricates the exact number the product
    exists to surface, so a missing value is a 422."""
    c, _ = api
    body = {k: v for k, v in PROFILE.items() if k != "sanctioned_load_kw"}
    assert (await c.post("/v1/sizing-runs", json=body)).status_code == 422
    assert (
        await c.post("/v1/sizing-runs", json={**PROFILE, "sanctioned_load_kw": 0})
    ).status_code == 422


async def test_unknown_field_in_the_profile_is_rejected(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """`extra="forbid"`. A field the API does not understand is a browser/API
    version skew, and silently ignoring it means a user's input vanished."""
    c, _ = api
    r = await c.post("/v1/sizing-runs", json={**PROFILE, "daytime_fraction": 0.6})
    assert r.status_code == 422


async def test_contradictory_ev_charging_is_rejected(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    c, _ = api
    r = await c.post(
        "/v1/sizing-runs",
        json={**PROFILE, "modifiers": ["EV_CHARGED_AT_NIGHT", "EV_CHARGED_BY_DAY"]},
    )
    assert r.status_code == 422


async def test_sizing_against_an_unknown_building_is_404(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    c, _ = api
    r = await c.post("/v1/sizing-runs", json={**PROFILE, "building_id": "nope"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Roof correction (FR-1.5)
# ---------------------------------------------------------------------------


async def test_usable_area_override_is_used_and_disclosed(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    c, _ = api
    r = (
        await c.post("/v1/sizing-runs", json={**PROFILE, "usable_area_m2_override": 60})
    ).json()
    assert r["usable_area_m2"] == 60.0
    assert r["usable_area_source"] == "USER_CORRECTED"
    assert r["roof_max_kwp"] == pytest.approx(5.0)  # 60 / 12


async def test_no_override_reports_the_segmented_area(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    c, _ = api
    r = (await c.post("/v1/sizing-runs", json=PROFILE)).json()
    assert r["usable_area_m2"] == 84.0
    assert r["usable_area_source"] == "SEGMENTED"


async def test_usable_area_override_cannot_exceed_the_roof(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """Refused, not clamped. If segmentation missed half the building then the
    roof footprint is wrong too, and the fix is re-analysis — not a number typed
    into a box outgrowing the polygon it describes. It is also the invariant the
    database enforces."""
    c, _ = api
    r = await c.post("/v1/sizing-runs", json={**PROFILE, "usable_area_m2_override": 500})
    assert r.status_code == 422
    assert "larger than" in str(r.json()["detail"])


# ---------------------------------------------------------------------------
# Persistence and privacy
# ---------------------------------------------------------------------------


async def test_run_id_is_opaque_and_not_a_database_key(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """ARCHITECTURE.md 8: a short-lived opaque identifier, so runs cannot be
    enumerated."""
    c, _ = api
    first = (await c.post("/v1/sizing-runs", json=PROFILE)).json()["run_id"]
    second = (await c.post("/v1/sizing-runs", json=PROFILE)).json()["run_id"]
    assert first != second
    assert len(first) == 43  # token_urlsafe(32)
    assert not first.isdigit()


async def test_persisted_run_carries_no_identifying_field(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """ARCHITECTURE.md 8. The schema has no column for these, and this is the
    test that notices if one is ever added and filled."""
    c, repo = api
    await c.post("/v1/sizing-runs", json=PROFILE)
    [run] = repo.saved

    flat = str(run).lower()
    for forbidden in ("consumer", "csn", "service_number", "address", "katpadi", "ocr", "name"):
        assert forbidden not in flat, f"persisted run mentions {forbidden!r}"

    assert set(run.input_profile_json) == {
        "monthly_units_kwh",
        "sanctioned_load_kw",
        "occupancy",
        "modifiers",
        "usable_area_m2",
        "usable_area_source",
        "yield_source",
    }


async def test_persisted_run_stores_exact_decimal_strings(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """PRD 8.1 is a to-the-rupee criterion; the audit trail does not get to be
    less exact than the answer was."""
    c, repo = api
    await c.post("/v1/sizing-runs", json=PROFILE)
    [run] = repo.saved
    assert isinstance(run.savings_range_json["lo"], str)
    Decimal(run.savings_range_json["lo"])  # parses exactly, no float round-trip
    assert run.expires_at is not None, "ARCHITECTURE.md 8: runs expire"
    assert isinstance(run.recommended_kwp, Decimal)


async def test_a_write_failure_does_not_cost_the_user_their_result() -> None:
    """The calculation succeeded and the household is entitled to the answer. A
    500 here would end a demo over a database hiccup while a correct result sat
    in memory."""
    app, repo = make_app(FakeRepository(fail_on_save=True))
    async with client(app) as c:
        r = await c.post("/v1/sizing-runs", json=PROFILE)
    assert r.status_code == 200
    assert r.json()["run_id"] is None
    assert r.json()["recommended"]["kwp"] > 0
    assert repo.saved == []


async def test_a_json_decimal_does_not_inherit_binary_float_error(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """0.1 in JSON must arrive as Decimal("0.1"), not as 0.1000000000000000055.
    Everything downstream of this is exact, so this boundary is where that could
    have been lost."""
    c, repo = api
    await c.post("/v1/sizing-runs", json={**PROFILE, "monthly_units_kwh": 565.1})
    [run] = repo.saved
    assert run.input_profile_json["monthly_units_kwh"] == "565.1"


# ---------------------------------------------------------------------------
# Rules disclosure
# ---------------------------------------------------------------------------


async def test_tariffs_current_discloses_dated_versioned_rules(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    c, _ = api
    r = await c.get("/v1/tariffs/current")
    assert r.status_code == 200
    body = r.json()
    assert body["tariff_version"] == "tn-domestic-2025-07-01"
    assert body["effective_from"] == "2025-07-01"
    assert body["category"] == "DOMESTIC"
    assert body["all_verified"] is False
    assert "bimonthly" in body["bimonthly_open_question"].lower()
    assert body["grid_disclosure"] == GRID_DISCLOSURE


async def test_tariff_slabs_are_published_as_exact_strings(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """Rates render as the order writes them. "4.7" where the order says "4.70"
    invites the question of what else was rounded."""
    c, _ = api
    slabs = (await c.get("/v1/tariffs/current")).json()["slabs"]
    assert [s["rate_inr_per_kwh"] for s in slabs] == ["0.00", "4.70", "6.30", "8.40", "11.55"]
    assert slabs[0]["label"] == "1-100"
    assert slabs[-1]["label"] == "401+"
    assert slabs[-1]["slab_to"] is None


async def test_tariffs_current_works_without_a_database(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """It reads the versioned JSON packs, which are the source of truth and ship
    with the wheel. The browser can still show which rules it would have used
    while the database is down."""
    c, _ = api
    assert (await c.get("/healthz")).status_code == 503
    assert (await c.get("/v1/tariffs/current")).status_code == 200


# ---------------------------------------------------------------------------
# Bill extraction
# ---------------------------------------------------------------------------


async def test_unsupported_upload_type_is_rejected(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    c, _ = api
    r = await c.post(
        "/v1/bill-extract",
        files={"file": ("bill.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert r.status_code == 415


async def test_oversized_upload_is_rejected_by_size_not_by_header() -> None:
    """ARCHITECTURE.md 8. Content-Length is not trustworthy, so the cap is
    enforced on bytes actually read."""
    app, _ = make_app(bill_upload_max_bytes=1024)
    async with client(app) as c:
        r = await c.post(
            "/v1/bill-extract",
            files={"file": ("bill.png", b"\x89PNG" + b"x" * 5000, "image/png")},
        )
    assert r.status_code == 413


async def test_empty_upload_is_rejected(api: tuple[httpx.AsyncClient, Any]) -> None:
    c, _ = api
    r = await c.post("/v1/bill-extract", files={"file": ("bill.pdf", b"", "application/pdf")})
    assert r.status_code == 400


async def test_bill_extraction_is_rate_limited_per_client() -> None:
    """ARCHITECTURE.md 8: "Limit bill-extraction requests by IP and size."""
    app, _ = make_app(bill_extract_per_minute=2)
    async with client(app) as c:
        files = {"file": ("bill.pdf", b"%PDF-1.4 not really", "application/pdf")}
        statuses = [
            (await c.post("/v1/bill-extract", files=files)).status_code for _ in range(4)
        ]
    assert statuses[-1] == 429
    assert 429 not in statuses[:2]


async def test_missing_extraction_backend_degrades_to_manual_entry(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """ARCHITECTURE.md 4.3: extraction is convenience, not product logic. The
    `extract` dependency group is absent from the API image on purpose, so this
    is the deployed behaviour and the browser already handles it by telling the
    user to type the values in."""
    c, _ = api
    try:
        import pypdf  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("pypdf is installed here, so extraction is available and this path is moot")

    r = await c.post(
        "/v1/bill-extract", files={"file": ("bill.pdf", b"%PDF-1.4", "application/pdf")}
    )
    assert r.status_code == 503
    assert "manual entry" in r.json()["detail"] or "Type the values" in r.json()["detail"]


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


async def test_only_the_configured_origin_is_allowed(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """ARCHITECTURE.md 9.2: "Configure CORS to permit only the web application's
    deployed origin."""
    c, _ = api
    allowed = await c.get("/healthz", headers={"Origin": ORIGIN})
    assert allowed.headers.get("access-control-allow-origin") == ORIGIN

    other = await c.get("/healthz", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_a_wildcard_cors_origin_is_refused_outright() -> None:
    """There is deliberately no value of CORS_ALLOW_ORIGINS that yields `*`. The
    one time that would matter is a deployed environment where somebody set it in
    a hurry."""
    with pytest.raises(ValueError, match="refused"):
        load_settings({"CORS_ALLOW_ORIGINS": "*"})
    with pytest.raises(ValueError, match="refused"):
        load_settings({"CORS_ALLOW_ORIGINS": "http://localhost:5173,*"})


# ---------------------------------------------------------------------------
# Traced roofs — FR-1.5 for addresses outside the precomputed pilot area
# ---------------------------------------------------------------------------

TRACED = {
    "traced_roof": {
        "lat": 12.9202,
        "lon": 79.1325,
        "roof_area_m2": 120,
        "usable_area_m2": 84,
    },
    "monthly_units_kwh": 565,
    "sanctioned_load_kw": 3,
    "occupancy": "PARTIAL",
    "modifiers": [],
}


async def test_traced_roof_sizes_without_any_building_row() -> None:
    """The whole point: an address nobody precomputed still gets an answer.

    The repository is emptied rather than merely unused, so this fails loudly if
    the route ever starts reaching for a row it should not need.
    """
    app, repo = make_app(FakeRepository(buildings={}))
    async with client(app) as c:
        r = await c.post("/v1/sizing-runs", json=TRACED)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["usable_area_m2"] == 84
    assert body["usable_area_source"] == "USER_TRACED"
    # No pvlib analysis can exist for a roof drawn thirty seconds ago.
    assert body["yield_source"] == "REGIONAL_FALLBACK"
    # PRD 5.2 does not get waived because the roof was hand-drawn.
    assert body["grid_feasibility"] == "NOT_VERIFIED"
    assert body["grid_disclosure"] == GRID_DISCLOSURE


async def test_traced_roof_is_not_persisted() -> None:
    """`sizing_runs.building_id` is a foreign key into `buildings`, and a traced
    roof has no row there. The run is skipped, not faked, and the household
    still gets the answer with a null run id."""
    app, repo = make_app(FakeRepository(buildings={}))
    async with client(app) as c:
        r = await c.post("/v1/sizing-runs", json=TRACED)
    assert r.status_code == 200
    assert r.json()["run_id"] is None
    assert repo.saved == []


async def test_a_precomputed_roof_is_still_persisted(api: tuple[httpx.AsyncClient, Any]) -> None:
    """Guards the branch above: skipping persistence must be specific to traced
    roofs, not something that quietly turned it off for everyone."""
    c, repo = api
    r = await c.post("/v1/sizing-runs", json=PROFILE)
    assert r.status_code == 200
    assert r.json()["run_id"] is not None
    assert len(repo.saved) == 1


async def test_building_id_and_traced_roof_are_mutually_exclusive(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """Accepting both would leave the route silently picking one, and which it
    picked would decide the household's answer."""
    c, _ = api
    r = await c.post("/v1/sizing-runs", json={**TRACED, "building_id": "bldg-demo-1"})
    assert r.status_code == 422


async def test_a_roof_is_required(api: tuple[httpx.AsyncClient, Any]) -> None:
    c, _ = api
    body = {k: v for k, v in TRACED.items() if k != "traced_roof"}
    r = await c.post("/v1/sizing-runs", json=body)
    assert r.status_code == 422


async def test_traced_usable_area_cannot_exceed_the_outline(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """The same invariant `ck_usable_within_roof` enforces on seeded roofs.
    A traced roof never reaches that table, so the model has to hold the line."""
    c, _ = api
    bad = {**TRACED, "traced_roof": {**TRACED["traced_roof"], "usable_area_m2": 200}}
    r = await c.post("/v1/sizing-runs", json=bad)
    assert r.status_code == 422


async def test_traced_roof_still_obeys_the_sanctioned_load_ceiling() -> None:
    """PRD 10: the recommendation never exceeds roof or sanctioned-load maximum.
    A large hand-drawn roof must not become a route around the connection cap."""
    app, _ = make_app(FakeRepository(buildings={}))
    big = {**TRACED, "traced_roof": {**TRACED["traced_roof"], "roof_area_m2": 900, "usable_area_m2": 900}}
    async with client(app) as c:
        r = await c.post("/v1/sizing-runs", json=big)
    assert r.status_code == 200
    body = r.json()
    assert body["sanctioned_load_max_kwp"] <= 3.0
    if body["recommended"] is not None:
        assert body["recommended"]["kwp"] <= body["feasible_max_kwp"]
    assert body["binding_constraint"] in {"SANCTIONED_LOAD", "BOTH"}
