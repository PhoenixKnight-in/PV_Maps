"""The sizing optimiser — ARCHITECTURE.md 5.1 and 7, build-order item 2.

    "Evaluate every allowed candidate kWp and choose the best-value option."
    "...returns the best-value size plus the entire comparison curve."

There is no model here and nothing is fitted. Every allowed size is evaluated
exactly, and the best one is returned along with all the others so the user can
see the shape of the trade-off rather than being handed a number to trust.

Pure: no database, no HTTP. Its only inputs are a confirmed profile, a roof
limit, and versioned assumption packs.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from pvmaps.sizing.assumptions import (
    Range,
    SolarAssumptions,
    SubsidySchedule,
    load_assumptions,
    load_subsidy,
)
from pvmaps.sizing.profiles import UsageProfile
from pvmaps.sizing.self_consumption import EnergySplit, split_generation
from pvmaps.tariff import solar_savings
from pvmaps.tariff.schedule import TariffSchedule

__all__ = [
    "KWP_STEP",
    "Candidate",
    "Recommendation",
    "Verdict",
    "optimise",
]

KWP_STEP = Decimal("0.5")
"""Panels and inverters come in discrete sizes. A continuous optimum would
return a capacity nobody can install."""

_ZERO = Decimal(0)
_RUPEE = Decimal("1")
_YEAR = Decimal("0.1")


class Verdict(StrEnum):
    RECOMMENDED = "RECOMMENDED"
    """Pays back even on the pessimistic bound."""

    MARGINAL = "MARGINAL"
    """Pays back on the optimistic bound but not the pessimistic one. The
    honest answer is 'it depends', and the UI must say which assumptions it
    depends on."""

    NOT_ECONOMIC = "NOT_ECONOMIC"
    """Does not pay back on any bound. PRD G2's honest zero.

    PRD 10: never let this sit alone in the UI. Pair it with what the household
    would need to change -- more daytime load, a higher tariff slab -- and with
    what the same panels are worth elsewhere. The verb is *route*, never
    *reject*."""

    NO_CAPACITY = "NO_CAPACITY"
    """Roof or sanctioned load leaves no installable size at all."""


@dataclass(frozen=True, slots=True)
class Candidate:
    kwp: Decimal
    split: EnergySplit

    annual_bill_savings: Range
    annual_export_credit: Range
    annual_om_cost: Range
    annual_net_benefit: Range

    gross_capex: Range
    subsidy: Decimal
    net_capex: Range

    npv: Range
    payback_years: Range | None
    """None when the pessimistic bound never pays back."""

    @property
    def annual_generation(self) -> Range:
        return self.split.generation * Decimal(12)

    @property
    def effective_rate(self) -> Range:
        """Rupees realised per kWh generated. Falls as the system saturates --
        this is the curve that shows why bigger is not better."""
        gen = self.annual_generation
        if gen.lo <= _ZERO:
            return Range.exact(0)
        return Range(
            self.annual_bill_savings.lo / gen.hi,
            self.annual_bill_savings.hi / gen.lo,
        )


@dataclass(frozen=True, slots=True)
class Recommendation:
    verdict: Verdict
    recommended: Candidate | None
    curve: tuple[Candidate, ...]

    roof_max_kwp: Decimal
    sanctioned_load_max_kwp: Decimal
    feasible_max_kwp: Decimal

    tariff_version: str
    assumptions_version: str
    subsidy_version: str
    assumptions_verified: bool

    yield_source: str
    """BUILDING when a pvlib analysis for this roof drove the generation figure,
    REGIONAL_FALLBACK when the assumptions pack's band did. The UI must not
    present the two with equal confidence."""

    @property
    def binding_constraint(self) -> str:
        """Which limit actually caps this household.

        PRD 11 beat 1 exists because the answer is so often 'the contract, not
        the roof' -- and no tool in the market says so.
        """
        if self.sanctioned_load_max_kwp < self.roof_max_kwp:
            return "SANCTIONED_LOAD"
        if self.roof_max_kwp < self.sanctioned_load_max_kwp:
            return "ROOF"
        return "BOTH"

    @property
    def is_economically_capped(self) -> bool:
        """True when the recommendation is smaller than what is physically and
        legally allowed -- i.e. the household should NOT max out its roof."""
        return self.recommended is not None and self.recommended.kwp < self.feasible_max_kwp


def _floor_to_step(kwp: Decimal) -> Decimal:
    """Down, never nearest. Rounding a 2.9 kW ceiling up to 3.0 recommends a
    system that exceeds the sanctioned load and dies at feasibility review."""
    return (kwp / KWP_STEP).to_integral_value(rounding=ROUND_DOWN) * KWP_STEP


def _npv(
    annual_benefit: Decimal,
    net_capex: Decimal,
    degradation_pct: Decimal,
    discount_pct: Decimal,
    years: int,
) -> Decimal:
    """Discounted lifetime value of one scalar scenario.

    Interval arithmetic is deliberately not used here. NPV is not monotonic in
    all of its inputs the way the earlier steps are, so the bounds are paired
    explicitly by the caller -- worst benefit with worst cost, and so on.
    """
    keep = (Decimal(100) - degradation_pct) / Decimal(100)
    rate = (Decimal(100) + discount_pct) / Decimal(100)

    total = -net_capex
    for year in range(1, years + 1):
        total += (annual_benefit * keep ** (year - 1)) / rate**year
    return total


def _evaluate(
    kwp: Decimal,
    profile: UsageProfile,
    tariff: TariffSchedule,
    a: SolarAssumptions,
    subsidy: SubsidySchedule,
    specific_yield: Range | None = None,
) -> Candidate:
    split = split_generation(kwp, profile, a, specific_yield=specific_yield)

    # solar_savings is monotonic non-decreasing in generation, so the bounds
    # map straight through without crossing.
    monthly_savings = Range(
        solar_savings(profile.monthly_units_kwh, split.self_consumed.lo, tariff).savings,
        solar_savings(profile.monthly_units_kwh, split.self_consumed.hi, tariff).savings,
    )
    annual_savings = monthly_savings * Decimal(12)
    annual_export = split.exported * a.export_rate * Decimal(12)
    annual_om = a.annual_om_per_kwp * kwp
    annual_benefit = annual_savings + annual_export - annual_om

    gross_capex = a.installed_cost_per_kwp * kwp
    subsidy_amount = subsidy.amount_for(kwp)
    net_capex = Range(
        max(_ZERO, gross_capex.lo - subsidy_amount),
        max(_ZERO, gross_capex.hi - subsidy_amount),
    )

    npv = Range(
        _npv(
            annual_benefit.lo,
            net_capex.hi,
            a.annual_degradation_pct.hi,
            a.discount_rate_pct.hi,
            a.system_lifetime_years,
        ),
        _npv(
            annual_benefit.hi,
            net_capex.lo,
            a.annual_degradation_pct.lo,
            a.discount_rate_pct.lo,
            a.system_lifetime_years,
        ),
    )

    payback: Range | None = None
    if annual_benefit.lo > _ZERO:
        payback = Range(
            (net_capex.lo / annual_benefit.hi).quantize(_YEAR, rounding=ROUND_HALF_UP),
            (net_capex.hi / annual_benefit.lo).quantize(_YEAR, rounding=ROUND_HALF_UP),
        )

    return Candidate(
        kwp=kwp,
        split=split,
        annual_bill_savings=annual_savings,
        annual_export_credit=annual_export,
        annual_om_cost=annual_om,
        annual_net_benefit=annual_benefit,
        gross_capex=gross_capex,
        subsidy=subsidy_amount,
        net_capex=net_capex,
        npv=npv,
        payback_years=payback,
    )


def optimise(
    profile: UsageProfile,
    roof_max_kwp: Decimal,
    tariff: TariffSchedule,
    assumptions: SolarAssumptions | None = None,
    subsidy: SubsidySchedule | None = None,
    specific_yield: Range | None = None,
) -> Recommendation:
    """Evaluate every installable size and return the best plus the full curve.

        recommendation = min(roof maximum, sanctioned-load maximum, economic optimum)

    The economic optimum is chosen on the PESSIMISTIC bound of NPV. Optimising
    on the midpoint would recommend a size that only pays back if the wide
    servable-fraction band lands favourably, and that band is the least
    knowable input in the whole calculation. A household should not be sold the
    system that works if everything goes right.

    `specific_yield` is the per-building annual kWh/kWp band from the pvlib
    pipeline. Omitted, the regional fallback band in the assumptions pack is
    used instead -- which is correct for a building the pipeline has not
    analysed, and is why `yield_source` is reported on the result.
    """
    a = assumptions or load_assumptions()
    s = subsidy or load_subsidy()

    if roof_max_kwp < _ZERO:
        raise ValueError(f"roof capacity cannot be negative: {roof_max_kwp}")

    feasible_max = _floor_to_step(min(roof_max_kwp, profile.roof_independent_ceiling_kwp()))

    # Heterogeneous by nature -- Decimal limits, string versions, bool flags --
    # so it is annotated rather than inferred as dict[str, object].
    common: dict[str, Any] = {
        "roof_max_kwp": roof_max_kwp,
        "sanctioned_load_max_kwp": profile.sanctioned_load_kw,
        "feasible_max_kwp": feasible_max,
        "tariff_version": tariff.version,
        "assumptions_version": a.version,
        "subsidy_version": s.version,
        "assumptions_verified": a.is_verified and s.is_verified,
        "yield_source": "BUILDING" if specific_yield is not None else "REGIONAL_FALLBACK",
    }

    if feasible_max < KWP_STEP:
        return Recommendation(verdict=Verdict.NO_CAPACITY, recommended=None, curve=(), **common)

    steps = int(feasible_max / KWP_STEP)
    curve = tuple(
        _evaluate(KWP_STEP * i, profile, tariff, a, s, specific_yield)
        for i in range(1, steps + 1)
    )

    best = max(curve, key=lambda c: (c.npv.lo, c.npv.hi, -c.kwp))

    if best.npv.lo > _ZERO:
        verdict = Verdict.RECOMMENDED
    elif max(c.npv.hi for c in curve) > _ZERO:
        verdict = Verdict.MARGINAL
        # Under MARGINAL the conservative bound is negative everywhere, so
        # ranking by it is meaningless -- rank by the optimistic bound and let
        # the UI carry the caveat.
        best = max(curve, key=lambda c: (c.npv.hi, -c.kwp))
    else:
        verdict = Verdict.NOT_ECONOMIC

    return Recommendation(
        verdict=verdict,
        recommended=best if verdict is not Verdict.NOT_ECONOMIC else None,
        curve=curve,
        **common,
    )
