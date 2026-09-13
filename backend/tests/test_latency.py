"""The two-second budget — PRD 7 and PRD 10.

    "Address-to-roof result should return in under two seconds for the
     precomputed pilot area."
    "Five pilot addresses return roof results in under two seconds."

WHAT THIS MEASURES: the share of that budget the application itself spends —
routing, the row-to-wire serialisation, and (for a sizing run) the whole
optimiser, every candidate size, every Decimal. The repository is faked, so the
database read and the network are NOT in the number.

WHAT IT IS THEREFORE FOR: catching the regression that makes the budget
impossible rather than proving it is met. An optimiser that starts evaluating ten
thousand candidates, or a serialiser that quantises in a loop, shows up here as a
multiple, not as a few milliseconds. Whether a real request lands under two
seconds is a question for a real PostGIS and `docker compose up` — the seeded
stack, over the pilot ward, on the demo machine.

The budgets below are deliberately loose. This suite runs on laptops and on CI
boxes under load, and a flaky timing test gets deleted rather than investigated.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from pvmaps.api.deps import get_repository
from pvmaps.api.main import create_app
from pvmaps.api.repository import BuildingRow
from pvmaps.api.settings import Settings
from pvmaps.pipeline.seed import PILOT_ROOFS, polygon_wkt_to_geojson
from tests.fakes import FakeRepository

ROOF_BUDGET_S = 0.25
"""One roof lookup. Twelve percent of the two seconds, for a route that is one
indexed read and two Decimal divisions."""

SIZING_BUDGET_S = 0.75
"""One full recommendation: every candidate size from 0.5 kWp to the feasible
maximum, each one priced through the telescopic tariff on both bounds."""

ATTEMPTS = 3
"""Best of three. A stop-the-world GC pause or a noisy CI neighbour is not a
latency regression, and this test only claims to catch the kind that is a
multiple rather than a jitter."""

PROFILE = {
    "monthly_units_kwh": 565,
    "sanctioned_load_kw": 3,
    "occupancy": "PARTIAL",
    "modifiers": [],
}


def pilot_rows() -> dict[str, BuildingRow]:
    """Every seeded pilot roof, as the API would have read it.

    From `PILOT_ROOFS` rather than a fixture: PRD 10's criterion is about the
    pilot addresses that actually exist, so if the pilot shrinks below five this
    test says so instead of timing a set of roofs nobody ships.
    """
    return {
        roof.building_id: BuildingRow(
            id=roof.building_id,
            geojson=polygon_wkt_to_geojson(roof.footprint_wkt),
            obstruction_geojson=roof.obstruction_geojson,
            roof_area_m2=roof.roof_area_m2,
            usable_area_m2=roof.usable_area_m2,
            typology=roof.typology,
            confidence=roof.confidence,
            analysis=None,
        )
        for roof in PILOT_ROOFS
    }


@pytest.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        Settings(
            database_url=None,
            cors_allow_origins=["http://localhost:5173"],
            log_level="warning",
        )
    )
    repo = FakeRepository(buildings=pilot_rows(), addresses=[])

    async def _repo() -> AsyncIterator[FakeRepository]:
        yield repo

    app.dependency_overrides[get_repository] = _repo
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _fastest(call: Any) -> tuple[float, httpx.Response]:
    best = float("inf")
    response = None
    for _ in range(ATTEMPTS):
        started = time.perf_counter()
        response = await call()
        best = min(best, time.perf_counter() - started)
    assert response is not None
    return best, response


async def test_the_pilot_still_holds_the_five_addresses_the_criterion_names() -> None:
    """PRD 10 measures five. Timing three of them would meet a different
    criterion."""
    assert len(PILOT_ROOFS) >= 5


async def test_every_pilot_roof_answers_well_inside_the_roof_budget(
    api: httpx.AsyncClient,
) -> None:
    for building_id in pilot_rows():
        elapsed, response = await _fastest(lambda b=building_id: api.get(f"/v1/buildings/{b}"))
        assert response.status_code == 200
        assert elapsed < ROOF_BUDGET_S, (
            f"{building_id} took {elapsed:.3f}s of the two-second budget before the "
            f"database was even involved"
        )


async def test_every_pilot_roof_can_be_sized_well_inside_the_budget(
    api: httpx.AsyncClient,
) -> None:
    """The optimiser is the only part of the request path that does real work, and
    it is the part that grows: candidates scale with the feasible maximum, and the
    VIT roof is two orders of magnitude larger than a house."""
    for building_id in pilot_rows():
        body = {"building_id": building_id, **PROFILE}
        elapsed, response = await _fastest(lambda b=body: api.post("/v1/sizing-runs", json=b))
        assert response.status_code == 200
        assert elapsed < SIZING_BUDGET_S, (
            f"sizing {building_id} took {elapsed:.3f}s; the whole address-to-result "
            f"flow is budgeted at two seconds including the database and the network"
        )


async def test_the_largest_pilot_roof_does_not_blow_up_the_curve(
    api: httpx.AsyncClient,
) -> None:
    """A sanctioned load is what bounds the candidate count, not the roof. The VIT
    roof could hold over a hundred kWp; if the curve ever started following the
    roof instead, this is where a 200-point curve would first be visible."""
    vit = max(pilot_rows().values(), key=lambda row: row.usable_area_m2)
    response = await api.post(
        "/v1/sizing-runs", json={"building_id": vit.id, **PROFILE, "sanctioned_load_kw": 150}
    )
    assert response.status_code == 200
    curve = response.json()["curve"]
    # 150 kW sanctioned / 0.5 kWp step is the widest curve Phase 1 can produce,
    # because sanctioned_load_kw is capped at 150 by the request schema.
    assert len(curve) <= 300
