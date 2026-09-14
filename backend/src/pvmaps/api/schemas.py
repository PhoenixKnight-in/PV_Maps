"""The wire contract — ARCHITECTURE.md 8.

    "Validate all form data with matching Zod browser schemas and Pydantic API
     schemas."

These mirror `web/src/schemas/sizing.ts` field for field. A divergence here
renders as a blank result panel rather than an error, so the two files change in
the same commit or not at all.

Two rules hold throughout:

**This module is the only place a Decimal becomes a float.** Everything upstream
is exact (PRD 10 (acceptance criteria)). JSON has no decimal type, so the conversion has to happen
somewhere; doing it here, once, at the boundary, means no calculation can
inherit binary error from a round-trip.

**Nothing inferred crosses as a bare number.** Bands travel as `RangeOut`,
single values that could have been inferred travel as `Estimate`. The shapes
make NFR-2 structural rather than something reviewers have to notice.

Imports pydantic only — no fastapi, no sqlalchemy — so
`scripts/build_demo_fallback.py` serialises through exactly the code path the
API uses, and the bundled demo fixture cannot drift from the live response.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pvmaps.estimate import Estimate
from pvmaps.sizing.assumptions import Range
from pvmaps.sizing.optimise import Candidate, Recommendation
from pvmaps.sizing.profiles import Occupancy, UsageModifier

__all__ = [
    "GRID_DISCLOSURE",
    "AddressOut",
    "BuildingOut",
    "CandidateOut",
    "RangeOut",
    "RecommendationOut",
    "SizingRequest",
    "SlabOut",
    "TariffSummaryOut",
    "TracedRoof",
    "serialise_candidate",
    "serialise_recommendation",
]

GRID_DISCLOSURE = (
    "Grid connection is not verified. Official TNPDCL feasibility is required "
    "before installation."
)
"""PRD 5.2: every Phase 1 result must carry this. The browser has its own copy
in GridDisclosure.jsx; this one travels with the payload so that any other
consumer of the API — an installer's own tooling, a CSV export — cannot receive
a recommendation without it."""

_RUPEE_2DP = Decimal("0.01")
_KWH_2DP = Decimal("0.01")
_RATE_4DP = Decimal("0.0001")
_YEAR_1DP = Decimal("0.1")


def _q(value: Decimal, quantum: Decimal) -> float:
    """Quantise, then cross into float.

    Both bounds of a range always get the same quantum, so rounding can never
    invert an interval.
    """
    return float(value.quantize(quantum, rounding=ROUND_HALF_UP))


class RangeOut(BaseModel):
    """A closed interval. Mirrors `sizing.assumptions.Range` and Zod's
    `RangeSchema`."""

    model_config = ConfigDict(frozen=True)

    lo: float
    hi: float

    @model_validator(mode="after")
    def _ordered(self) -> RangeOut:
        if self.lo > self.hi:
            raise ValueError(f"inverted range: lo={self.lo} > hi={self.hi}")
        return self

    @classmethod
    def of(cls, r: Range, quantum: Decimal = _RUPEE_2DP) -> RangeOut:
        return cls(lo=_q(r.lo, quantum), hi=_q(r.hi, quantum))


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class TracedRoof(BaseModel):
    """A roof outline drawn by hand on imagery, with its area already computed.

    Areas are sent rather than derived from the polygon server-side on purpose:
    the browser computed them from the exact shape the user saw and accepted,
    and recomputing here from a re-projected polygon would let the two disagree
    by a few square metres with no way to tell which the household actually
    agreed to.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    lat: Decimal = Field(ge=-90, le=90)
    lon: Decimal = Field(ge=-180, le=180)

    roof_area_m2: Decimal = Field(gt=0, le=100_000)
    """The outlined footprint."""

    usable_area_m2: Decimal = Field(gt=0, le=100_000)
    """What is left after setbacks and obstructions. Must not exceed the
    footprint — the same invariant `ck_usable_within_roof` enforces on seeded
    roofs, checked here because a traced roof never reaches that table."""

    @model_validator(mode="after")
    def _usable_within_roof(self) -> TracedRoof:
        if self.usable_area_m2 > self.roof_area_m2:
            raise ValueError("usable_area_m2 cannot exceed roof_area_m2")
        return self


class SizingRequest(BaseModel):
    """The confirmed profile. ARCHITECTURE.md 6: this, not the upload, is the
    calculation input.

    Bounds mirror `UsageProfileSchema` in the browser. They are repeated rather
    than trusted: the browser's copy is a courtesy to the user, this one is the
    actual contract, and anything can POST here.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    building_id: str | None = Field(default=None, min_length=1, max_length=64)
    """A precomputed pilot roof. Exactly one of this and `traced_roof` is set."""

    traced_roof: TracedRoof | None = None
    """FR-1.5 taken to its conclusion: a roof the household outlined themselves
    on imagery, for an address outside the precomputed pilot area.

    This is deliberately NOT live segmentation. PRD 9 says "do not run
    segmentation live on stage" and ARCHITECTURE.md 1 says the request path must
    not load SAM2 or create a roof mask — so the geometry arrives already drawn,
    by a person, and the response labels it `USER_TRACED` so no reader can
    mistake it for a surveyed footprint.
    """

    monthly_units_kwh: Decimal = Field(ge=0, le=5000)
    """Units for ONE month. PRD 10 (must verify) is still open on the bimonthly cycle, so the
    browser asks for a monthly figure and no conversion happens server-side — a
    silent halving here would be invisible and wrong."""

    sanctioned_load_kw: Decimal = Field(gt=0, le=150)
    """Never defaulted. PRD 2.1 constraint #2: this is a hard cap on plant size,
    and guessing it fabricates the exact number the product exists to surface."""

    occupancy: Occupancy
    modifiers: list[UsageModifier] = Field(default_factory=list)

    usable_area_m2_override: Decimal | None = Field(default=None, ge=0, le=100_000)
    """FR-1.5 roof correction. Segmentation on flat Indian roofs is imperfect and
    the PRD says to report that rather than hide it. The response echoes back
    which area was used."""

    @field_validator("modifiers")
    @classmethod
    def _no_contradictory_ev(cls, v: list[UsageModifier]) -> list[UsageModifier]:
        if UsageModifier.EV_CHARGED_AT_NIGHT in v and UsageModifier.EV_CHARGED_BY_DAY in v:
            raise ValueError("an EV cannot be charged exclusively at night and by day")
        return v

    @model_validator(mode="after")
    def _exactly_one_roof(self) -> SizingRequest:
        """A roof comes from the pilot table or from the user's own outline,
        never both and never neither.

        Accepting both would leave the route silently choosing one, and which it
        chose would decide the household's answer.
        """
        if (self.building_id is None) == (self.traced_roof is None):
            raise ValueError("provide exactly one of building_id or traced_roof")
        return self


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class AddressOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    building_id: str | None
    lat: float
    lon: float


class BuildingOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    geojson: dict[str, Any] | None
    obstruction_geojson: dict[str, Any] | None = None

    roof_area_m2: float
    usable_area_m2: float

    roof_max_kwp: float
    """The conservative cap — see `sizing.capacity.roof_max_kwp` for why it is
    the low bound of `roof_max_kwp_band` rather than its midpoint."""

    roof_max_kwp_band: RangeOut
    """What might physically fit, honestly. The UI may show this; the
    calculation uses `roof_max_kwp`."""

    typology: str
    confidence: float

    annual_yield_kwh_per_kwp: Estimate[float]
    """From `roof_analyses` when the pvlib pipeline has run for this roof,
    otherwise the regional band from the assumptions pack. `source` distinguishes
    them, and that difference is visible rather than implied."""

    yield_source: Literal["BUILDING", "REGIONAL_FALLBACK"]
    analysis_version: str | None = None


class CandidateOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    kwp: float
    annual_generation: RangeOut

    self_consumed_kwh: RangeOut
    """PER MONTH. The browser labels it 'kWh/mo' and the demo bundle has always
    carried it that way, so the name stays as contracted; the annual figures PRD
    5.2 asks for are the two fields below."""

    exported_kwh: RangeOut
    """PER MONTH — see above."""

    annual_self_consumed_kwh: RangeOut
    annual_exported_kwh: RangeOut

    annual_bill_savings: RangeOut
    annual_export_credit: RangeOut
    """FR-4.3: import offset and export credit stay separate line items, never
    summed into one 'savings' figure."""

    annual_om_cost: RangeOut
    annual_net_benefit: RangeOut

    gross_capex: RangeOut
    subsidy: float
    net_capex: RangeOut

    npv: RangeOut
    payback_years: RangeOut | None
    """None when the pessimistic bound never pays back. Not zero, and not a
    large number — 'never' is the honest answer and it has to stay
    distinguishable."""

    effective_rate: RangeOut
    """Rupees realised per kWh generated. Falls as the system saturates, which is
    the whole argument for recommending less than the roof allows."""


class RecommendationOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str | None = None
    """Opaque and short-lived (ARCHITECTURE.md 8). None when the calculation
    succeeded but the run could not be persisted — the result is still valid and
    is still returned."""

    verdict: Literal["RECOMMENDED", "MARGINAL", "NOT_ECONOMIC", "NO_CAPACITY"]
    recommended: CandidateOut | None
    curve: list[CandidateOut]

    roof_max_kwp: float
    sanctioned_load_max_kwp: float
    feasible_max_kwp: float
    binding_constraint: Literal["ROOF", "SANCTIONED_LOAD", "BOTH"]
    is_economically_capped: bool

    usable_area_m2: float
    usable_area_source: Literal["SEGMENTED", "USER_CORRECTED", "USER_TRACED"]
    """FR-1.5: "Using your figure instead of ours. The result will say so."
    This field is the API saying so."""

    tariff_version: str
    assumptions_version: str
    subsidy_version: str
    assumptions_verified: bool
    yield_source: Literal["BUILDING", "REGIONAL_FALLBACK"]

    grid_feasibility: Literal["NOT_VERIFIED"] = "NOT_VERIFIED"
    """Phase 1 has exactly one possible value. ARCHITECTURE.md 11: no component
    may call a network estimate 'verified' without an authorised source, a
    timestamp and a policy version, and Phase 1 has none of the three. The field
    is a Literal so a future edit cannot widen it without the type changing."""

    grid_disclosure: str = GRID_DISCLOSURE


class SlabOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    slab_from: int
    slab_to: int | None
    rate_inr_per_kwh: str
    """A string, not a float. These are the published rates; rendering 4.7 where
    the order says 4.70 invites the question of what else we rounded."""


class TariffSummaryOut(BaseModel):
    """GET /v1/tariffs/current — the dated rule summary the UI discloses."""

    model_config = ConfigDict(frozen=True)

    tariff_version: str
    category: str
    effective_from: str
    billing_period_months: int
    currency: str
    slabs: list[SlabOut]
    source: str
    tariff_verified: bool

    subsidy_version: str
    subsidy_verified: bool
    assumptions_version: str
    assumptions_verified: bool

    all_verified: bool
    """False while any pack is still UNVERIFIED_AGAINST_PRIMARY_SOURCE. The
    results screen shows its provisional banner on this."""

    bimonthly_open_question: str
    grid_disclosure: str = GRID_DISCLOSURE


# ---------------------------------------------------------------------------
# Serialisers — domain objects in, wire models out
# ---------------------------------------------------------------------------


def serialise_candidate(c: Candidate) -> CandidateOut:
    twelve = Decimal(12)
    return CandidateOut(
        kwp=float(c.kwp),
        annual_generation=RangeOut.of(c.annual_generation, _KWH_2DP),
        self_consumed_kwh=RangeOut.of(c.split.self_consumed, _KWH_2DP),
        exported_kwh=RangeOut.of(c.split.exported, _KWH_2DP),
        annual_self_consumed_kwh=RangeOut.of(c.split.self_consumed * twelve, _KWH_2DP),
        annual_exported_kwh=RangeOut.of(c.split.exported * twelve, _KWH_2DP),
        annual_bill_savings=RangeOut.of(c.annual_bill_savings),
        annual_export_credit=RangeOut.of(c.annual_export_credit),
        annual_om_cost=RangeOut.of(c.annual_om_cost),
        annual_net_benefit=RangeOut.of(c.annual_net_benefit),
        gross_capex=RangeOut.of(c.gross_capex),
        subsidy=_q(c.subsidy, _RUPEE_2DP),
        net_capex=RangeOut.of(c.net_capex),
        npv=RangeOut.of(c.npv),
        payback_years=(
            None if c.payback_years is None else RangeOut.of(c.payback_years, _YEAR_1DP)
        ),
        effective_rate=RangeOut.of(c.effective_rate, _RATE_4DP),
    )


def serialise_recommendation(
    r: Recommendation,
    *,
    usable_area_m2: Decimal,
    usable_area_source: Literal["SEGMENTED", "USER_CORRECTED", "USER_TRACED"],
    run_id: str | None = None,
) -> RecommendationOut:
    return RecommendationOut(
        run_id=run_id,
        verdict=r.verdict.value,
        recommended=serialise_candidate(r.recommended) if r.recommended else None,
        curve=[serialise_candidate(c) for c in r.curve],
        roof_max_kwp=float(r.roof_max_kwp),
        sanctioned_load_max_kwp=float(r.sanctioned_load_max_kwp),
        feasible_max_kwp=float(r.feasible_max_kwp),
        binding_constraint=r.binding_constraint,  # type: ignore[arg-type]
        is_economically_capped=r.is_economically_capped,
        usable_area_m2=_q(usable_area_m2, _KWH_2DP),
        usable_area_source=usable_area_source,
        tariff_version=r.tariff_version,
        assumptions_version=r.assumptions_version,
        subsidy_version=r.subsidy_version,
        assumptions_verified=r.assumptions_verified,
        yield_source=r.yield_source,  # type: ignore[arg-type]
    )
