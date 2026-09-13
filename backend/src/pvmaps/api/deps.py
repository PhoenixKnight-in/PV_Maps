"""FastAPI dependencies.

The repository is reached only through `get_repository`, which is what lets
tests/test_api.py run the whole API against an in-memory repository with no
PostgreSQL at all — and, more usefully, is what keeps a route handler from
quietly opening a session and running its own SQL.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from pvmaps.api.repository import PostgresRepository, Repository
from pvmaps.api.settings import Settings
from pvmaps.sizing.assumptions import (
    SolarAssumptions,
    SubsidySchedule,
    load_assumptions,
    load_subsidy,
)
from pvmaps.tariff.schedule import TariffSchedule, load_schedule

__all__ = [
    "AssumptionsDep",
    "RepositoryDep",
    "SettingsDep",
    "SubsidyDep",
    "TariffDep",
    "get_repository",
    "get_settings",
]

TARIFF_VERSION = "tn-domestic-2025-07-01"
"""Phase 1 pilot is one domestic category in one ward. `latest_for("DOMESTIC")`
would pick by today's date, which means a clock change could silently alter a
demo's numbers; pinning it keeps the rule pack a deliberate choice. Swap this for
date-based selection when a second schedule exists and the bimonthly question
(PRD 10 (must verify)) is closed."""


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


async def get_repository(request: Request) -> AsyncIterator[Repository]:
    """A repository bound to one request-scoped session.

    With no DATABASE_URL configured there is no repository to give, and every
    route that needs one answers 503. That is deliberate: an API that cannot read
    roof rows should say so rather than fall back to a regional average and
    present it as a roof result. The browser has its own bundled fallback for
    this case (ARCHITECTURE.md 9.3) and `GET /healthz` is what tells it to use
    it.
    """
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No database is configured for this API instance, so no roof data "
                "can be read."
            ),
        )
    async with factory() as session:
        yield PostgresRepository(session)


def get_tariff() -> TariffSchedule:
    return load_schedule(TARIFF_VERSION)


def get_assumptions() -> SolarAssumptions:
    return load_assumptions()


def get_subsidy() -> SubsidySchedule:
    return load_subsidy()


SettingsDep = Annotated[Settings, Depends(get_settings)]
RepositoryDep = Annotated[Repository, Depends(get_repository)]
TariffDep = Annotated[TariffSchedule, Depends(get_tariff)]
AssumptionsDep = Annotated[SolarAssumptions, Depends(get_assumptions)]
SubsidyDep = Annotated[SubsidySchedule, Depends(get_subsidy)]
