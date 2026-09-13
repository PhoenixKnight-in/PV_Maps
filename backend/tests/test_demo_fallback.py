"""The bundled demo fixture must not drift from the engine — ARCHITECTURE.md 9.3.

    "If external geocoding or imagery fails, the web app still demonstrates the
     full Bill-to-Roof calculation from its local pilot data."

That promise is only worth something if the bundled numbers are the numbers the
engine currently produces. A stale fixture does not fail loudly; it shows a judge
a recommendation the running code would no longer make, and the one moment it
matters is the moment nobody can debug it.

So: regenerate on any engine change.

    uv run --group dev python scripts/build_demo_fallback.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pvmaps.api.schemas import GRID_DISCLOSURE, BuildingOut, RecommendationOut

BUNDLE = (
    Path(__file__).resolve().parents[2]
    / "web" / "public" / "demo-fallback" / "pilot-addresses.json"
)


@pytest.fixture(scope="module")
def bundle() -> dict:
    if not BUNDLE.exists():
        pytest.fail(
            f"{BUNDLE} is missing. Generate it:\n"
            "  uv run --group dev python scripts/build_demo_fallback.py"
        )
    return json.loads(BUNDLE.read_text(encoding="utf-8"))


def test_the_bundle_matches_what_the_engine_produces_now(bundle: dict) -> None:
    """Regenerate and compare. Any difference means the fixture is stale."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import build_demo_fallback

    before = json.dumps(bundle, sort_keys=True)
    build_demo_fallback.main()
    after = json.dumps(json.loads(BUNDLE.read_text(encoding="utf-8")), sort_keys=True)

    assert before == after, (
        "The bundled demo fallback is stale -- the engine now produces different "
        "numbers. It has just been regenerated in place; commit the change.\n"
        "  uv run --group dev python scripts/build_demo_fallback.py"
    )


def test_the_bundle_validates_against_the_wire_schemas(bundle: dict) -> None:
    """The browser parses this with the same Zod schemas it parses live responses
    with. If it does not satisfy the Pydantic side, it will not satisfy Zod
    either, and the failure mode there is a blank panel rather than an error."""
    for payload in bundle["buildings"].values():
        BuildingOut.model_validate(payload)
    for payload in bundle["recommendations"].values():
        RecommendationOut.model_validate(payload)


def test_the_bundle_rehearses_both_outcomes(bundle: dict) -> None:
    """PRD G2 and PRD 10: the honest zero is a feature, and it must never stand
    alone. A demo bundle carrying only the happy case cannot rehearse the pair."""
    verdicts = {r["verdict"] for r in bundle["recommendations"].values()}
    assert "RECOMMENDED" in verdicts
    assert "NOT_ECONOMIC" in verdicts


def test_the_bundle_shows_the_contract_beating_the_roof(bundle: dict) -> None:
    """PRD 11 beat 1 has to work offline too."""
    rec = bundle["recommendations"]["bldg-demo-1"]
    assert rec["binding_constraint"] == "SANCTIONED_LOAD"
    assert rec["sanctioned_load_max_kwp"] < rec["roof_max_kwp"]
    assert rec["is_economically_capped"] is True
    assert rec["recommended"]["kwp"] <= rec["feasible_max_kwp"]


def test_the_vit_roof_carries_no_rupee_figure(bundle: dict) -> None:
    """PRD 11: "For VIT, show 'estimated physical rooftop potential: 2.1 MWp'
    only. Do not claim annual rupee savings without VIT's actual consumption and
    tariff data." PRD 12 lists an unverified VIT savings claim as a named risk.

    So the roof is in the bundle and the recommendation deliberately is not.
    """
    vit = next(b for b in bundle["buildings"] if "demo-3" in b)
    assert bundle["buildings"][vit]["roof_max_kwp"] > 0
    assert vit not in bundle["recommendations"]


def test_every_bundled_result_carries_the_disclosure(bundle: dict) -> None:
    assert bundle["_grid_disclosure"] == GRID_DISCLOSURE
    for rec in bundle["recommendations"].values():
        assert rec["grid_feasibility"] == "NOT_VERIFIED"
        assert rec["grid_disclosure"] == GRID_DISCLOSURE


def test_bundled_addresses_all_resolve_to_a_bundled_building(bundle: dict) -> None:
    """An address whose building is missing is a dead end in the one flow that is
    supposed to survive everything else failing."""
    for address in bundle["addresses"]:
        assert address["building_id"] in bundle["buildings"]


def test_the_bundle_contains_no_identifying_data(bundle: dict) -> None:
    """NFR-1. This file ships to every browser that loads the app."""
    flat = json.dumps(bundle).lower()
    for forbidden in ("consumer", "csn", "service_number", "@", "phone"):
        assert forbidden not in flat, f"demo bundle contains {forbidden!r}"


def test_five_pilot_addresses_are_bundled(bundle: dict) -> None:
    """PRD 10 end-to-end: "Five pilot addresses return roof results in under two
    seconds." Five is the criterion, so five is what the pilot -- and the bundle
    that has to survive the database being down -- actually holds."""
    assert len(bundle["addresses"]) == 5
    assert len({a["id"] for a in bundle["addresses"]}) == 5


def test_every_bundled_roof_carries_an_outline(bundle: dict) -> None:
    """ARCHITECTURE.md 9.3: the offline path has to show the same roof the live
    path would. A recommendation floating over no building is not the flow."""
    for building_id, payload in bundle["buildings"].items():
        geojson = payload["geojson"]
        assert geojson is not None, f"{building_id} has no footprint to draw"
        assert geojson["type"] == "Polygon"
        ring = geojson["coordinates"][0]
        assert len(ring) >= 4 and ring[0] == ring[-1], f"{building_id} ring is not closed"
        # Vellore. A transposed lat/lon pair puts the pilot in the Arabian Sea and
        # still renders, which is exactly why this is asserted rather than eyeballed.
        for lon, lat in ring:
            assert 79.0 < lon < 79.3, f"{building_id} longitude {lon} is not in the pilot area"
            assert 12.8 < lat < 13.1, f"{building_id} latitude {lat} is not in the pilot area"


def test_a_bundled_roof_explains_its_lost_area(bundle: dict) -> None:
    """FR-1.2 and FR-1.6: obstructions are persisted as geometry, not folded into
    a number. FR-1.5 then lets the user argue with them -- which is impossible if
    all the browser ever receives is a smaller usable area.

    Each marked obstruction must also lie inside the roof it belongs to. The
    pilot marks are placed by hand, and a metre typed in the wrong direction
    produces a water tank on the neighbour's roof.
    """
    marked = {
        bid: payload
        for bid, payload in bundle["buildings"].items()
        if payload.get("obstruction_geojson")
    }
    assert marked, "no pilot roof carries obstruction geometry"

    for bid, payload in marked.items():
        ring = payload["geojson"]["coordinates"][0]
        lons = [c[0] for c in ring]
        lats = [c[1] for c in ring]
        features = payload["obstruction_geojson"]["features"]
        assert features
        for feature in features:
            assert feature["properties"]["area_m2"] > 0
            assert feature["properties"]["label"]
            for lon, lat in feature["geometry"]["coordinates"][0]:
                assert min(lons) <= lon <= max(lons), f"{bid}: obstruction outside the footprint"
                assert min(lats) <= lat <= max(lats), f"{bid}: obstruction outside the footprint"
        assert payload["usable_area_m2"] < payload["roof_area_m2"]


def test_the_bundle_rehearses_every_verdict_the_engine_can_return(bundle: dict) -> None:
    """PRD 9 week 2 item 9 and PRD 10.

    MARGINAL is the one that gets skipped. It is the answer that says "it depends
    on assumptions you cannot check", it is the hardest sentence to say on stage,
    and a bundle without it means nobody has rehearsed saying it.
    """
    verdicts = {r["verdict"] for r in bundle["recommendations"].values()}
    assert verdicts == {"RECOMMENDED", "MARGINAL", "NOT_ECONOMIC"}


def test_the_bundle_rehearses_a_roof_bound_household_too(bundle: dict) -> None:
    """PRD G4 asks for roof maximum, sanctioned-load maximum and recommendation to
    be compared. If every rehearsed address is capped by its contract, the demo
    only ever tells half of that story."""
    bindings = {
        bid: bundle["recommendations"][bid]["binding_constraint"]
        for bid in bundle["recommendations"]
    }
    assert "ROOF" in bindings.values()
    assert "SANCTIONED_LOAD" in bindings.values()


def test_the_bundle_rehearses_an_expected_new_load(bundle: dict) -> None:
    """PRD 5.1 asks for expected load additions, and FR-4 sizes for them. A
    modifier that no bundled scenario exercises is a code path that has never run
    on the machine the demo runs on."""
    import sys
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "scripts"))
    import build_demo_fallback

    assert any(p.modifiers for p in build_demo_fallback.PROFILES.values())
