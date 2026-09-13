"""The confirmed usage profile — what the browser actually submits.

ARCHITECTURE.md 6:

    "A bill upload is not the source of truth. The confirmed profile submitted
     to the sizing endpoint is the calculation input."

So this module models what the user *confirmed*, never what OCR *guessed*. The
extraction endpoint fills a form; the human corrects it; the corrected values
arrive here. Nothing in `pvmaps.sizing` ever sees a bill image, a consumer
number, or raw OCR text (ARCHITECTURE.md 8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from pvmaps.sizing.assumptions import Range, SolarAssumptions

__all__ = ["Occupancy", "UsageModifier", "UsageProfile"]


class Occupancy(StrEnum):
    """How much of the day someone is actually home drawing load.

    Four coarse buckets, not a slider. A slider would imply the user knows a
    number they cannot know without an interval meter, and would produce a
    false sense of precision in the result.
    """

    EMPTY_WEEKDAYS = "EMPTY_WEEKDAYS"
    PARTIAL = "PARTIAL"
    HOME_ALL_DAY = "HOME_ALL_DAY"
    DAYTIME_HEAVY = "DAYTIME_HEAVY"


class UsageModifier(StrEnum):
    """Expected new loads (ARCHITECTURE.md 4.1 step 5).

    Sizing for the load a household is about to acquire is the difference
    between a system that fits and one that is obsolete in a year.
    """

    DAYTIME_AC_PLANNED = "DAYTIME_AC_PLANNED"
    EV_CHARGED_AT_NIGHT = "EV_CHARGED_AT_NIGHT"
    EV_CHARGED_BY_DAY = "EV_CHARGED_BY_DAY"


@dataclass(frozen=True, slots=True)
class UsageProfile:
    """A confirmed bill profile plus daytime-use answers."""

    monthly_units_kwh: Decimal
    """Confirmed consumption for one month. If the bill is bimonthly the caller
    converts BEFORE constructing this -- and PRD 10 (must verify) says that conversion is
    still an open question, so it must not happen silently in here."""

    occupancy: Occupancy
    sanctioned_load_kw: Decimal
    modifiers: frozenset[UsageModifier] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.monthly_units_kwh < 0:
            raise ValueError(f"consumption cannot be negative: {self.monthly_units_kwh}")
        if self.sanctioned_load_kw <= 0:
            raise ValueError(
                f"sanctioned load must be positive, got {self.sanctioned_load_kw}. "
                "It is a hard cap on plant size (PRD 2.1 constraint #2) and a "
                "missing value must be surfaced to the user, not defaulted."
            )
        if UsageModifier.EV_CHARGED_AT_NIGHT in self.modifiers and (
            UsageModifier.EV_CHARGED_BY_DAY in self.modifiers
        ):
            raise ValueError("an EV cannot be charged exclusively at night and by day")

    @property
    def annual_units_kwh(self) -> Decimal:
        return self.monthly_units_kwh * 12

    def servable_fraction(self, a: SolarAssumptions) -> Range:
        """Fraction of consumption solar can realistically displace.

        Archetype band, shifted by any modifiers, clamped to the configured
        floor and ceiling. The band stays wide on purpose: this is the single
        largest source of uncertainty in the whole recommendation, and
        narrowing it without an interval meter would be fiction.
        """
        band = a.servable_archetypes[self.occupancy.value]
        for m in sorted(self.modifiers):
            band = band + a.servable_modifiers[m.value]
        return band.clamp(a.servable_floor, a.servable_ceiling)

    def roof_independent_ceiling_kwp(self) -> Decimal:
        """The cap that has nothing to do with the roof.

        PRD 2.1: "plant kW <= service connection's sanctioned load". PRD 11
        beat 1 is this line and nothing else: the confident roof number gets
        struck through by a number from a contract.
        """
        return self.sanctioned_load_kw
