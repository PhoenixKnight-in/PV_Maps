"""GET /v1/search — pilot-address lookup.

ARCHITECTURE.md 9.3: resolves against our own `addresses` table, not a live
geocoder. One less thing that can fail on stage, and it is why this route has no
network dependency at all.

ARCHITECTURE.md 8: the query string is a fragment of somebody's home address.
It is never logged — not here, and not by uvicorn's access log, which
`api.logging.configure_logging` disables for this reason.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from pvmaps.api.deps import RepositoryDep, SettingsDep
from pvmaps.api.schemas import AddressOut

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[AddressOut], summary="Search pilot addresses")
async def search_addresses(
    repo: RepositoryDep,
    settings: SettingsDep,
    q: str = Query(
        min_length=2,
        max_length=200,
        description="Address fragment. Matched against normalised pilot addresses.",
    ),
) -> list[AddressOut]:
    rows = await repo.search_addresses(q, settings.search_limit)
    return [
        AddressOut(
            id=row.id,
            display_name=row.display_name,
            building_id=row.building_id,
            lat=row.lat,
            lon=row.lon,
        )
        for row in rows
    ]
