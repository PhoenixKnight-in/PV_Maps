"""Split generation into what the household uses and what leaves the house.

ARCHITECTURE.md 5.1:

    "Self-consumption model | Convert yield and daytime-use profile into
     self-used and exported energy ranges"

This is the module that decides whether a bigger system is worth anything. Once
generation exceeds what the household can absorb, every additional kWh is
exported -- and export is NOT valued at the retail slab rate. Getting this wrong
in the optimistic direction is how oversized systems get sold.

Pure. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pvmaps.sizing.assumptions import Range, SolarAssumptions
from pvmaps.sizing.profiles import UsageProfile

__all__ = ["EnergySplit", "split_generation"]

_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class EnergySplit:
    """One month's energy, banded."""

    generation: Range
    self_consumed: Range
    exported: Range
    servable_headroom: Range
    """Consumption solar could have displaced but did not, because the system
    is too small. Positive headroom means a larger system still has somewhere
    to put its output."""

    @property
    def self_consumption_ratio(self) -> Range:
        """Share of generation the household actually keeps."""
        if self.generation.hi <= _ZERO:
            return Range.exact(0)
        return Range(
            self.self_consumed.lo / self.generation.hi,
            self.self_consumed.hi / self.generation.lo
            if self.generation.lo > _ZERO
            else Decimal(1),
        ).clamp(_ZERO, Decimal(1))

    @property
    def is_saturated(self) -> bool:
        """True when even the optimistic case exports. The system has outgrown
        the household."""
        return self.exported.lo > _ZERO


def monthly_generation(
    kwp: Decimal, a: SolarAssumptions, specific_yield: Range | None = None
) -> Range:
    """kWh generated in an average month by a `kwp` system.

    `specific_yield` (kWh/kWp/yr) is the per-building pvlib band from
    roof_analyses. When it is absent the configured regional band is used --
    that band is the fallback, not the answer (ARCHITECTURE.md 2).

    Flat twelfth of the annual figure, deliberately. The monthly shape exists in
    roof_analyses.monthly_yield_json, but this module compares generation
    against a *monthly bill*, and TN bills are issued on a bimonthly cycle whose
    boundaries do not align with calendar months (PRD 10 (must verify), still open). Aligning
    a real monthly generation curve to a billing period that is not yet modelled
    would buy precision in one term while the other stays coarse.
    """
    if kwp < _ZERO:
        raise ValueError(f"system size cannot be negative: {kwp}")
    return ((specific_yield or a.specific_yield) * kwp) / Decimal(12)


def split_generation(
    kwp: Decimal,
    profile: UsageProfile,
    a: SolarAssumptions,
    generation: Range | None = None,
    specific_yield: Range | None = None,
) -> EnergySplit:
    """Divide a month's generation into self-consumed and exported bands.

        servable = monthly_units x servable_fraction
        self_consumed = min(generation, servable)
        exported = generation - self_consumed

    The `min` is elementwise on the bounds, and that is deliberate. Pairing our
    low generation with their high servable capacity would manufacture a
    self-consumption figure neither bound supports.

    `generation` overrides the month's generation band outright. The usual way
    in is `specific_yield`, the per-building annual kWh/kWp band from
    roof_analyses, which is scaled by `monthly_generation`.
    """
    gen = monthly_generation(kwp, a, specific_yield) if generation is None else generation
    servable = Range.exact(profile.monthly_units_kwh) * profile.servable_fraction(a)

    # min() is monotonic in both arguments, so self-consumption's bounds pair
    # elementwise: lowest generation against lowest servable load, and so on.
    self_consumed = gen.cap_at(servable)

    # Export and headroom are DIFFERENCES, and differences cross their bounds
    # (see Range.__sub__). Least export is the lowest generation against the
    # highest servable load; most export is the reverse. Pairing these
    # elementwise produces an inverted interval -- which is how this bug was
    # caught -- and, worse, would understate export for a saturated system.
    exported = Range(
        max(_ZERO, gen.lo - servable.hi),
        max(_ZERO, gen.hi - servable.lo),
    )
    headroom = Range(
        max(_ZERO, servable.lo - gen.hi),
        max(_ZERO, servable.hi - gen.lo),
    )

    return EnergySplit(
        generation=gen,
        self_consumed=self_consumed,
        exported=exported,
        servable_headroom=headroom,
    )
