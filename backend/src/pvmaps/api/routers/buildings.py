"""GET /v1/buildings/{id} — precomputed roof geometry, area and yield.

PRD 7 budgets two seconds from address to roof result. This route is a single
indexed primary-key read plus one lateral join; the arithmetic is two Decimal
divisions. Nothing here segments, rasterises or calls pvlib — ARCHITECTURE.md 1
puts all of that in the offline plane.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, status

from pvmaps.api.assemble import building_out
from pvmaps.api.deps import AssumptionsDep, RepositoryDep
from pvmaps.api.schemas import BuildingOut

router = APIRouter(tags=["roofs"])


@router.get(
    "/buildings/{building_id}",
    response_model=BuildingOut,
    summary="Precomputed roof result for one building",
    responses={404: {"description": "No analysed roof with that id"}},
)
async def get_building(
    repo: RepositoryDep,
    assumptions: AssumptionsDep,
    building_id: str = Path(min_length=1, max_length=64),
) -> BuildingOut:
    row = await repo.get_building(building_id)
    if row is None:
        # The id is not secret, but it is not guessable either, and a pilot area
        # has a fixed building list — so a miss is a stale link or a typo, not
        # something to paper over with a default roof.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No analysed roof with that id.",
        )
    return building_out(row, assumptions)
