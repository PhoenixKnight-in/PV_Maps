"""Generate web/public/demo-fallback/pilot-addresses.json from the real engine.

ARCHITECTURE.md 9.3:

    "Keep the validated pilot addresses, roof results, and bill profiles bundled
     into the local demo environment. If external geocoding or imagery fails, the
     web app still demonstrates the full Bill-to-Roof calculation from its local
     pilot data."

Generated, never hand-written. A hand-written fixture drifts from the engine
silently, and the one moment it matters is the moment nobody can debug it.

Two things keep the drift out, and both are structural rather than disciplined:

* The roofs come from `pipeline.seed.PILOT_ROOFS` — the same tuple the database
  seeder writes. The bundle and the seeded database cannot describe different
  buildings.
* The payloads come from `api.schemas` and `api.assemble` — the same serialisers
  the live routes use. A field added to the API appears here; a field renamed
  here fails to validate.

    uv run --group dev python scripts/build_demo_fallback.py
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from pvmaps.api.assemble import building_out
from pvmaps.api.repository import BuildingRow
from pvmaps.api.schemas import GRID_DISCLOSURE, serialise_recommendation
from pvmaps.pipeline.seed import PILOT_ROOFS, PilotRoof, polygon_wkt_to_geojson
from pvmaps.sizing import (
    Occupancy,
    UsageModifier,
    UsageProfile,
    load_assumptions,
    load_subsidy,
    optimise,
)
from pvmaps.sizing.capacity import roof_max_kwp
from pvmaps.tariff import load_schedule

OUT = (
    Path(__file__).resolve().parents[2]
    / "web" / "public" / "demo-fallback" / "pilot-addresses.json"
)

TARIFF = load_schedule("tn-domestic-2025-07-01")
ASSUMPTIONS = load_assumptions()
SUBSIDY = load_subsidy()

# Four profiles, deliberately, and they do not all pay back. A demo that only
# shows the happy case is not demonstrating the product -- PRD G2 makes the
# honest zero a feature, and PRD 10 says never let it stand alone.
#
# PRD 9 week 2 item 9 asks for low-daytime-use, normal-household and
# high-daytime-use or EV-ready scenarios to be tested. One pilot address each,
# so the scenario that breaks is a scenario somebody can open:
#
#   demo-1  normal household, the contract caps the roof     RECOMMENDED
#   demo-2  low daytime use on the free slab, honest zero    NOT_ECONOMIC
#   demo-4  daytime-heavy, EV charged by day, small roof     RECOMMENDED, roof-bound
#   demo-5  home all day but few units                       MARGINAL
#
# There is no entry for the VIT roof. PRD 11: show "estimated physical rooftop
# potential" only, and attach no rupee figure until VIT's actual tariff,
# sanctioned demand and consumption are known.
PROFILES: dict[str, UsageProfile] = {
    "bldg-demo-1": UsageProfile(
        monthly_units_kwh=Decimal(565),
        occupancy=Occupancy.PARTIAL,
        sanctioned_load_kw=Decimal(3),
    ),
    "bldg-demo-2": UsageProfile(
        monthly_units_kwh=Decimal(95),
        occupancy=Occupancy.EMPTY_WEEKDAYS,
        sanctioned_load_kw=Decimal(3),
    ),
    "bldg-demo-4": UsageProfile(
        monthly_units_kwh=Decimal(780),
        occupancy=Occupancy.DAYTIME_HEAVY,
        sanctioned_load_kw=Decimal(5),
        modifiers=frozenset({UsageModifier.EV_CHARGED_BY_DAY}),
    ),
    "bldg-demo-5": UsageProfile(
        monthly_units_kwh=Decimal(130),
        occupancy=Occupancy.HOME_ALL_DAY,
        sanctioned_load_kw=Decimal(3),
    ),
}


def as_building_row(roof: PilotRoof) -> BuildingRow:
    """The row the API would have read, had the database been up.

    `analysis=None` on purpose: a freshly seeded database has no `roof_analyses`
    row until the pipeline's `yield` command runs, so the bundle shows exactly
    what the API would return in that state — REGIONAL_FALLBACK, and saying so.

    The footprint IS carried. It is the same polygon the seeder writes, converted
    the way PostGIS would convert it, so the map still draws a roof when the
    database is unreachable. Leaving it out would mean the one path that is
    supposed to survive everything else failing (ARCHITECTURE.md 9.3) shows a
    recommendation floating over no building.
    """
    return BuildingRow(
        id=roof.building_id,
        geojson=polygon_wkt_to_geojson(roof.footprint_wkt),
        obstruction_geojson=roof.obstruction_geojson,
        roof_area_m2=roof.roof_area_m2,
        usable_area_m2=roof.usable_area_m2,
        typology=roof.typology,
        confidence=roof.confidence,
        analysis=None,
    )


def main() -> None:
    addresses: list[dict[str, Any]] = []
    buildings: dict[str, Any] = {}
    recommendations: dict[str, Any] = {}

    for roof in PILOT_ROOFS:
        addresses.append(
            {
                "id": roof.id,
                "display_name": roof.display_name,
                "building_id": roof.building_id,
                "lat": roof.lat,
                "lon": roof.lon,
            }
        )
        row = as_building_row(roof)
        buildings[roof.building_id] = building_out(row, ASSUMPTIONS).model_dump(mode="json")

        profile = PROFILES.get(roof.building_id)
        if profile is None:
            print(f"{roof.display_name[:52]:54} (physical potential only -- PRD 11)")
            continue

        usable = Decimal(str(roof.usable_area_m2))
        result = optimise(
            profile,
            roof_max_kwp=roof_max_kwp(usable, ASSUMPTIONS),
            tariff=TARIFF,
            assumptions=ASSUMPTIONS,
            subsidy=SUBSIDY,
        )
        recommendations[roof.building_id] = serialise_recommendation(
            result,
            usable_area_m2=usable,
            usable_area_source="SEGMENTED",
            # No run_id: nothing was persisted, because there was no database.
            # The browser falls back to "preview" and that is accurate.
            run_id=None,
        ).model_dump(mode="json")

        print(
            f"{roof.display_name[:52]:54} {result.verdict.value:13} "
            f"roof={result.roof_max_kwp} sanctioned={result.sanctioned_load_max_kwp} "
            f"rec={result.recommended.kwp if result.recommended else '-'}"
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "_generated_by": "backend/scripts/build_demo_fallback.py",
                "_warning": "Generated. Do not edit by hand -- regenerate instead.",
                "_roofs_from": "pvmaps.pipeline.seed.PILOT_ROOFS (same as the database seeder)",
                "_grid_disclosure": GRID_DISCLOSURE,
                "addresses": addresses,
                "buildings": buildings,
                "recommendations": recommendations,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
