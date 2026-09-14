"""The FastAPI application. `docker/api.Dockerfile` runs `pvmaps.api.main:app`.

ARCHITECTURE.md 5.2 fixes the Phase 1 surface, and it is deliberately short:

    GET  /v1/search?q=                   Pilot-address search
    GET  /v1/buildings/{id}              Roof geometry, usable area, yield
    POST /v1/sizing-runs                 Confirmed bill profile → recommendation
    POST /v1/bill-extract                Optional temporary extraction
    GET  /v1/tariffs/current             Current dated rule summary
    GET  /healthz                        Health check

    "The Phase 1 API has no transformer, quota, allocation, or grid-eligibility
     endpoint."

It has none. `pvmaps.phase2` exists, is tested, and is imported by nothing here —
ARCHITECTURE.md 11 is the boundary and this module is where it is kept.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from pvmaps import __version__
from pvmaps.api.deps import TARIFF_VERSION, get_assumptions, get_subsidy
from pvmaps.api.logging import access_log_middleware, configure_logging
from pvmaps.api.ratelimit import SlidingWindowLimiter
from pvmaps.api.routers import bill_extract, buildings, locate, search, sizing, tariffs
from pvmaps.api.settings import Settings, load_settings
from pvmaps.db.session import create_engine, create_session_factory
from pvmaps.tariff.schedule import load_schedule

__all__ = ["app", "create_app"]

log = structlog.get_logger("pvmaps.api")

PILOT_PROBE_SQL = text("SELECT count(*) FROM buildings")
"""What `/healthz` asks the database. Counting roofs rather than running
`SELECT 1`: the failure the demo actually suffers is a reachable database with no
schema or no pilot data, and `SELECT 1` reports both of those as healthy."""

DESCRIPTION = """
Bill-aware rooftop solar sizing for Tamil Nadu.

Every sizing result carries `grid_feasibility: "NOT_VERIFIED"` and the official
feasibility disclosure. Phase 1 does not and cannot verify a grid connection;
that is Grid Passport, and it needs authorised TNPDCL data that does not exist
yet.

Figures are ranges wherever the input was a bill without interval data. A range
is the honest shape of the answer, not a hedge.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the pool, and fail loudly on a bad rule pack.

    The rule packs are loaded here rather than on first request so that a
    malformed tariff JSON stops the container at startup. A schedule with a gap
    between slabs silently under-bills every consumer above the gap, and the
    worst moment to discover that is mid-demo on the first request.
    """
    settings: Settings = app.state.settings

    tariff = load_schedule(TARIFF_VERSION)
    assumptions = get_assumptions()
    subsidy = get_subsidy()
    all_verified = tariff.is_verified and assumptions.is_verified and subsidy.is_verified

    app.state.session_factory = None
    if settings.has_database:
        assert settings.database_url is not None
        app.state.engine = create_engine(settings.database_url, echo=settings.sql_echo)
        app.state.session_factory = create_session_factory(app.state.engine)
    else:
        app.state.engine = None
        log.warning(
            "no_database_configured",
            detail="roof routes will answer 503; the browser falls back to its bundled pilot data",
        )

    log.info(
        "api_started",
        version=__version__,
        tariff_version=tariff.version,
        assumptions_version=assumptions.version,
        subsidy_version=subsidy.version,
        assumptions_verified=all_verified,
        database=settings.has_database,
    )
    if not all_verified:
        # Loud, every boot, until someone reads the primary sources. PRD 12 lists
        # an overstated savings figure as the high-severity risk.
        log.warning(
            "rule_packs_unverified",
            detail=(
                "one or more rule packs is still UNVERIFIED_AGAINST_PRIMARY_SOURCE; "
                "results are indicative and the UI shows a provisional banner"
            ),
        )

    try:
        yield
    finally:
        if app.state.engine is not None:
            await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="PV Maps",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        # ARCHITECTURE.md 3: the typed calculation contract and its OpenAPI
        # documentation are a deliverable, not a side effect.
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    # Per-application, not module-level: shared mutable module state would mean
    # two apps in one process silently sharing an upload budget.
    app.state.bill_limiter = SlidingWindowLimiter(settings.bill_extract_per_minute)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=False,
        # Phase 1 has no authentication and no cookies (ARCHITECTURE.md 8), so
        # there is nothing for a credentialed cross-origin request to carry.
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        max_age=600,
    )
    app.middleware("http")(access_log_middleware)

    app.include_router(search.router, prefix="/v1")
    app.include_router(buildings.router, prefix="/v1")
    app.include_router(sizing.router, prefix="/v1")
    app.include_router(bill_extract.router, prefix="/v1")
    app.include_router(tariffs.router, prefix="/v1")
    app.include_router(locate.router, prefix="/v1")

    @app.get("/healthz", tags=["ops"], summary="Liveness and pilot-data readiness")
    async def healthz(response: Response) -> dict[str, Any]:
        """503 unless a roof can actually be read, and that is the useful behaviour.

        `web/src/api/client.ts` calls this to decide whether to use its bundled
        pilot data (ARCHITECTURE.md 9.3). An API that answered 200 while unable
        to read a single roof row would keep the browser waiting on requests that
        cannot succeed, instead of falling back to a demo that works.

        Which is why the probe counts pilot roofs rather than running `SELECT 1`.
        Three states fail that way and each has a different fix, so each is named
        rather than flattened into "unreachable":

            not_configured   no DATABASE_URL; the browser uses its bundle
            unreachable      the database is not answering
            schema_missing   it is answering, but `alembic upgrade head` has not run
            no_pilot_data    migrated and empty; the seeder has not run

        A `SELECT 1` probe cannot tell the last two apart from a healthy database.
        A demo that trusts it discovers the difference on the first roof lookup,
        in front of an audience.
        """
        db: str
        factory = getattr(app.state, "session_factory", None)
        if factory is None:
            db = "not_configured"
        else:
            try:
                async with factory() as session:
                    result = await session.execute(PILOT_PROBE_SQL)
                    roofs = result.scalar_one()
                db = "ok" if roofs else "no_pilot_data"
            except ProgrammingError as exc:
                # The connection worked; the table did not exist. Reporting this
                # as "unreachable" sends an operator to look at the network.
                db = "schema_missing"
                log.error("healthz_schema_missing", error=type(exc).__name__)
            except Exception as exc:  # the reason is reported, never raised
                db = "unreachable"
                log.error("healthz_database_unreachable", error=type(exc).__name__)

        healthy = db == "ok"
        if not healthy:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ok" if healthy else "degraded",
            "version": __version__,
            "database": db,
            "phase": 1,
        }

    return app


app = create_app()
