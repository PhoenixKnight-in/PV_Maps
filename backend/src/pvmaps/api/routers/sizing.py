"""POST /v1/sizing-runs — the calculation request path, ARCHITECTURE.md 7.

    1. Browser sends the confirmed bill fields and daytime-use answers.
    2. API obtains the dated tariff and subsidy schedules.
    3. API calculates roof and sanctioned-load limits.
    4. API evaluates candidate sizes from 0.5 kWp to the feasible maximum.
    5. API returns the best-value size plus the entire comparison curve.

The confirmed profile is the calculation input, never the upload
(ARCHITECTURE.md 6). The optimiser itself is pure and lives in `pvmaps.sizing`;
this module's whole job is to fetch one precomputed roof row, decide which area
and which yield band to use, and persist what was calculated.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException, status

from pvmaps.api.assemble import choose_yield
from pvmaps.api.deps import AssumptionsDep, RepositoryDep, SettingsDep, SubsidyDep, TariffDep
from pvmaps.api.repository import BuildingRow, Repository, SizingRunRecord
from pvmaps.api.schemas import (
    RecommendationOut,
    SizingRequest,
    TracedRoof,
    serialise_recommendation,
)
from pvmaps.api.settings import Settings
from pvmaps.sizing.assumptions import Range
from pvmaps.sizing.capacity import roof_max_kwp
from pvmaps.sizing.optimise import Recommendation, optimise
from pvmaps.sizing.profiles import UsageProfile

router = APIRouter(tags=["sizing"])
log = structlog.get_logger("pvmaps.sizing")


def _new_run_id() -> str:
    """ARCHITECTURE.md 8: "a short-lived, opaque sizing-run identifier rather
    than exposing database identifiers." 32 bytes of urlsafe entropy is 43
    characters, which is what `sizing_runs.id` is sized for."""
    return secrets.token_urlsafe(32)


@router.post(
    "/sizing-runs",
    response_model=RecommendationOut,
    status_code=status.HTTP_200_OK,
    summary="Bill-aware recommended system size, plus the whole value curve",
    responses={
        404: {"description": "No analysed roof with that building id"},
        422: {"description": "The confirmed profile is not usable as calculation input"},
        503: {"description": "No database configured, so no roof data can be read"},
    },
)
async def create_sizing_run(
    body: SizingRequest,
    repo: RepositoryDep,
    settings: SettingsDep,
    tariff: TariffDep,
    assumptions: AssumptionsDep,
    subsidy: SubsidyDep,
) -> RecommendationOut:
    if body.traced_roof is not None:
        # The household drew this one. Nothing is read from or written to the
        # buildings table: there is no row, and inventing one would turn a
        # hand-drawn outline into something a later reader takes for survey.
        row = _row_from_traced(body.traced_roof)
        usable_area: Decimal = body.traced_roof.usable_area_m2
        area_source: Literal["SEGMENTED", "USER_CORRECTED", "USER_TRACED"] = "USER_TRACED"
    else:
        row = await repo.get_building(body.building_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No analysed roof with that id.",
            )
        usable_area, area_source = _resolve_usable_area(body, row.roof_area_m2, row.usable_area_m2)

    # Identical for both paths. A traced roof has no pvlib analysis, so this
    # resolves to the regional band and the response says REGIONAL_FALLBACK —
    # the same admission a seeded-but-unanalysed roof gets.
    choice = choose_yield(row, assumptions)

    profile = UsageProfile(
        monthly_units_kwh=body.monthly_units_kwh,
        occupancy=body.occupancy,
        sanctioned_load_kw=body.sanctioned_load_kw,
        modifiers=frozenset(body.modifiers),
    )

    result = optimise(
        profile,
        roof_max_kwp=roof_max_kwp(usable_area, assumptions),
        tariff=tariff,
        assumptions=assumptions,
        subsidy=subsidy,
        specific_yield=choice.specific_yield,
    )

    run_id = await _persist(repo, settings, body, result, usable_area, area_source)

    return serialise_recommendation(
        result,
        usable_area_m2=usable_area,
        usable_area_source=area_source,
        run_id=run_id,
    )


def _row_from_traced(traced: TracedRoof) -> BuildingRow:
    """Adapt a hand-drawn outline to the shape the rest of the route expects.

    `analysis=None` is the load-bearing field: it routes `choose_yield` to the
    regional band, which is the only honest yield for a roof whose tilt, azimuth
    and shading nobody has measured.

    `confidence` is 0.0 rather than a flattering default. The number is not an
    estimate of anything we computed — we did no extraction here — and a
    non-zero value would imply we had.
    """
    return BuildingRow(
        id="traced",
        geojson=None,
        obstruction_geojson=None,
        roof_area_m2=float(traced.roof_area_m2),
        usable_area_m2=float(traced.usable_area_m2),
        typology="unknown",
        confidence=0.0,
        analysis=None,
    )


def _resolve_usable_area(
    body: SizingRequest, roof_area_m2: float, segmented_usable_m2: float
) -> tuple[Decimal, Literal["SEGMENTED", "USER_CORRECTED"]]:
    """FR-1.5 — the user may correct the usable area, within the roof we found.

    An override above the detected roof footprint is refused rather than clamped.
    If segmentation missed half the building then `roof_area_m2` is wrong too,
    and the answer is to re-run the pipeline on that roof, not to let a number
    typed into a box outgrow the polygon it is supposed to describe. It is also
    the invariant the database enforces (`ck_usable_within_roof`), and an API
    that accepts what its own schema rejects fails later and less clearly.
    """
    if body.usable_area_m2_override is None:
        return Decimal(str(segmented_usable_m2)), "SEGMENTED"

    override = body.usable_area_m2_override
    roof = Decimal(str(roof_area_m2))
    if override > roof:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Usable roof area of {override} m2 is larger than the {roof} m2 "
                f"roof we detected. If the outline is wrong, the roof needs "
                f"re-analysing rather than the usable area raising."
            ),
        )
    return override, "USER_CORRECTED"


async def _persist(
    repo: Repository,
    settings: Settings,
    body: SizingRequest,
    result: Recommendation,
    usable_area: Decimal,
    area_source: str,
) -> str | None:
    """Store the run for reproducibility (NFR-4), and never fail the request for it.

    The calculation has already succeeded and the household is entitled to the
    answer. A write failure is an operational problem, so it is logged loudly and
    `run_id` comes back None — which the response model documents. Returning a
    500 here would mean a demo dies on a database hiccup while holding a correct
    result in memory.

    What goes in: confirmed units, occupancy archetype, sanctioned load,
    modifiers, the area used. What does not, and has no column to go in: consumer
    number, name, address, bill image, OCR text (ARCHITECTURE.md 8).

    A traced roof is not persisted. `sizing_runs.building_id` is a foreign key
    into `buildings`, and a hand-drawn outline has no row there — writing one
    would mean inserting a fabricated building to satisfy a constraint. The
    household still gets the full answer with `run_id: None`, which the response
    model already documents and the browser already handles.

    This does cost NFR-4 reproducibility for traced runs. Recovering it means a
    nullable FK plus somewhere to keep the outline, which is a migration and a
    schema decision, not something to smuggle in here.
    """
    if body.building_id is None:
        log.info("sizing_run_not_persisted_traced_roof", reason="no building row to reference")
        return None

    recommended = result.recommended
    run = SizingRunRecord(
        id=_new_run_id(),
        building_id=body.building_id,
        tariff_version=result.tariff_version,
        subsidy_version=result.subsidy_version,
        assumptions_version=result.assumptions_version,
        input_profile_json={
            "monthly_units_kwh": str(body.monthly_units_kwh),
            "sanctioned_load_kw": str(body.sanctioned_load_kw),
            "occupancy": body.occupancy.value,
            "modifiers": sorted(m.value for m in body.modifiers),
            "usable_area_m2": str(usable_area),
            "usable_area_source": area_source,
            "yield_source": result.yield_source,
        },
        roof_max_kwp=result.roof_max_kwp,
        sanctioned_load_max_kwp=result.sanctioned_load_max_kwp,
        recommended_kwp=recommended.kwp if recommended else None,
        verdict=result.verdict.value,
        self_consumed_kwh_range_json=_range_json(
            recommended.split.self_consumed if recommended else None
        ),
        exported_kwh_range_json=_range_json(
            recommended.split.exported if recommended else None
        ),
        savings_range_json=_range_json(
            recommended.annual_bill_savings if recommended else None
        ),
        payback_range_years_json=(
            _range_json(recommended.payback_years)
            if recommended and recommended.payback_years
            else None
        ),
        curve_json=[
            {
                "kwp": str(c.kwp),
                "annual_bill_savings": {
                    "lo": str(c.annual_bill_savings.lo),
                    "hi": str(c.annual_bill_savings.hi),
                },
                "npv": {"lo": str(c.npv.lo), "hi": str(c.npv.hi)},
            }
            for c in result.curve
        ],
        expires_at=datetime.now(UTC) + timedelta(days=settings.sizing_run_ttl_days),
    )

    try:
        await repo.save_sizing_run(run)
    except Exception as exc:
        log.error("sizing_run_not_persisted", error=type(exc).__name__, building_id=run.building_id)
        return None
    return run.id


def _range_json(r: Range | None) -> dict[str, str]:
    """A stored band, as exact decimal strings.

    Strings rather than JSON numbers: these rows exist for reproducibility, and a
    stored float would mean a replayed run could differ from the original in the
    last place. PRD 10 (acceptance criteria) is a to-the-rupee criterion and it is not worth weakening
    in the audit trail. `{}` for "there was no recommendation to record", which
    the NOT_ECONOMIC and NO_CAPACITY verdicts both produce.
    """
    return {} if r is None else {"lo": str(r.lo), "hi": str(r.hi)}
