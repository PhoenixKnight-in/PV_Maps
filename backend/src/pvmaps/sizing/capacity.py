"""Usable roof area → installable kWp. PRD FR-1.3 into FR-4.

One short module, on its own, because this conversion is the seam between the
geometry plane and the money plane and it is the easiest place in the system to
be quietly wrong. Everything downstream treats `roof_max_kwp` as a hard
physical cap, so the only safe error here is an understatement.

Pure: the area band comes from the versioned assumptions pack (NFR-4), and
nothing here touches a database, a raster, or a clock.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from pvmaps.sizing.assumptions import Range, SolarAssumptions

__all__ = ["kwp_band", "roof_max_kwp"]

_ZERO = Decimal(0)
_KWP = Decimal("0.01")


def _d(x: Decimal | int | float | str) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def kwp_band(usable_area_m2: Decimal | int | float, a: SolarAssumptions) -> Range:
    """The honest interval of what fits on `usable_area_m2`.

    Wide, because array packing on a flat Indian roof genuinely is. The low
    bound pairs the area with the most space-hungry layout.
    """
    area = _d(usable_area_m2)
    if area < _ZERO:
        raise ValueError(f"usable roof area cannot be negative: {area}")
    if area == _ZERO:
        return Range.exact(0)
    return Range.exact(area) / a.area_per_kwp_m2


def roof_max_kwp(usable_area_m2: Decimal | int | float, a: SolarAssumptions) -> Decimal:
    """The physical cap, taken from the CONSERVATIVE end of `kwp_band`.

    Deliberately the low bound, which is the area band's *high* bound -- the
    most space each kWp might need. Two reasons, and they point the same way:

    1. This number is consumed as a ceiling. `optimise` takes
       min(roof, sanctioned load) and never proposes a size above it, so an
       overstated ceiling does not produce a visible range -- it produces a
       recommendation for a system that does not fit the roof it was sized for.
       That failure surfaces at the installer's site visit, after the
       household has been told a payback figure.

    2. PRD 12 lists overstated savings as the high-severity risk. A roof
       maximum is the first number on the screen (PRD 11 beat 1) and it anchors
       everything after it.

    The optimistic bound is not discarded -- `kwp_band` returns it, and the UI
    can say "9.3-12.4 kWp may physically fit" while this caps the calculation.
    """
    return kwp_band(usable_area_m2, a).lo.quantize(_KWP, rounding=ROUND_DOWN)


def usable_area_for_kwp(kwp: Decimal | int | float, a: SolarAssumptions) -> Decimal:
    """Inverse of `roof_max_kwp`, on the same conservative bound.

    Used to state how much roof a recommended system actually needs, which is
    the question an installer asks next.
    """
    return (_d(kwp) * a.area_per_kwp_m2.hi).quantize(_KWP, rounding=ROUND_HALF_UP)
