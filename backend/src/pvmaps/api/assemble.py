"""Stored row → wire model. The one place the fallback decision is made.

Both `GET /v1/buildings/{id}` and `POST /v1/sizing-runs` need to answer the same
question: does this roof have a pvlib analysis, or are we about to apply a
regional band to it? Answering it in two places is how a building ends up
described one way by one endpoint and another way by the next.

Kept out of `schemas.py` on purpose: this module imports the repository DTOs,
the repository imports SQLAlchemy, and `schemas.py` has to stay importable with
pydantic alone so `scripts/build_demo_fallback.py` can serialise through it.
"""

from __future__ import annotations

from decimal import Decimal

from pvmaps.api.repository import BuildingRow
from pvmaps.api.schemas import BuildingOut, RangeOut
from pvmaps.estimate import Estimate
from pvmaps.sizing.assumptions import Range, SolarAssumptions
from pvmaps.sizing.capacity import kwp_band, roof_max_kwp

__all__ = ["YieldChoice", "building_out", "choose_yield"]

_REGIONAL_CONFIDENCE = 0.5
"""A regional band applied to one unanalysed roof. Half, not 0.8: the band
itself is published, but the claim that it describes *this* roof — its tilt, its
azimuth, its shading — is not."""


class YieldChoice:
    """Which yield figure is in play, and how to describe it honestly.

    `specific_yield` is None for the regional fallback, which is what `optimise`
    expects: passing None makes it use the assumptions pack and report
    `yield_source="REGIONAL_FALLBACK"`, so the two stay consistent by
    construction rather than by both being set correctly.
    """

    __slots__ = ("estimate", "source", "specific_yield", "version")

    def __init__(
        self,
        estimate: Estimate[float],
        specific_yield: Range | None,
        source: str,
        version: str | None,
    ) -> None:
        self.estimate = estimate
        self.specific_yield = specific_yield
        self.source = source
        self.version = version


def choose_yield(row: BuildingRow, a: SolarAssumptions) -> YieldChoice:
    """Per-building pvlib output if the pipeline has run, else the regional band.

    Note that both come back as `source="inferred"`. That is not laziness about
    the published band: the band is published *for inland Tamil Nadu*, and
    asserting it for one specific roof — whose tilt, azimuth and shading nobody
    has measured — is an inference. `Estimate` refuses to carry a non-inferred
    value with an open band for exactly this reason, and it is right to.
    """
    if row.analysis is not None:
        ra = row.analysis
        return YieldChoice(
            estimate=Estimate[float](
                value=ra.value,
                lo=ra.lo,
                hi=ra.hi,
                source="inferred",
                confidence=ra.confidence,
                note=f"pvlib analysis {ra.version} for this roof",
            ),
            specific_yield=Range.of(ra.lo, ra.hi),
            source="BUILDING",
            version=ra.version,
        )

    band = a.specific_yield
    return YieldChoice(
        estimate=Estimate[float](
            value=float(band.mid),
            lo=float(band.lo),
            hi=float(band.hi),
            source="inferred",
            confidence=_REGIONAL_CONFIDENCE,
            as_of=a.effective_from,
            note=(
                f"Regional band for {a.region or 'the pilot region'} "
                f"({a.version}). This roof has not been analysed individually."
            ),
        ),
        specific_yield=None,
        source="REGIONAL_FALLBACK",
        version=None,
    )


def building_out(row: BuildingRow, a: SolarAssumptions) -> BuildingOut:
    usable = Decimal(str(row.usable_area_m2))
    choice = choose_yield(row, a)
    return BuildingOut(
        id=row.id,
        geojson=row.geojson,
        obstruction_geojson=row.obstruction_geojson,
        roof_area_m2=row.roof_area_m2,
        usable_area_m2=row.usable_area_m2,
        roof_max_kwp=float(roof_max_kwp(usable, a)),
        roof_max_kwp_band=RangeOut.of(kwp_band(usable, a), Decimal("0.01")),
        typology=row.typology,
        confidence=row.confidence,
        annual_yield_kwh_per_kwp=choice.estimate,
        yield_source=choice.source,  # type: ignore[arg-type]
        analysis_version=choice.version,
    )
