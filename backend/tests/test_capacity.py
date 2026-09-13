"""Usable area → kWp. Small module, load-bearing conversion.

This is the seam between the geometry plane and the money plane. `roof_max_kwp`
is consumed as a hard ceiling by `optimise`, so an overstated value does not show
up as a wide range — it shows up as a recommendation for a system that does not
fit the roof it was sized for, discovered at the installer's site visit after the
household has been quoted a payback.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pvmaps.sizing import load_assumptions
from pvmaps.sizing.capacity import kwp_band, roof_max_kwp, usable_area_for_kwp

A = load_assumptions()


def test_the_cap_is_the_conservative_end_of_the_band() -> None:
    """Not the midpoint, and not the optimistic bound. 84 m2 at 9-12 m2/kWp is a
    7.0-9.33 kWp band, and 7.0 is what the calculation may assume."""
    band = kwp_band(84, A)
    assert roof_max_kwp(84, A) == Decimal("7.00")
    assert band.lo == pytest.approx(Decimal(7))
    assert band.hi > band.lo


def test_a_roof_with_no_usable_area_supports_nothing() -> None:
    assert roof_max_kwp(0, A) == Decimal("0.00")
    assert kwp_band(0, A).hi == 0


def test_negative_area_is_refused_rather_than_clamped() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        roof_max_kwp(-1, A)


def test_the_inverse_agrees_with_the_cap() -> None:
    """"How much roof does the recommended system need?" is the next question an
    installer asks, and it must not contradict the cap we just gave them."""
    for kwp in (Decimal("1.5"), Decimal("3"), Decimal("6.5")):
        area = usable_area_for_kwp(kwp, A)
        assert roof_max_kwp(area, A) >= kwp - Decimal("0.01")


@given(area=st.decimals(min_value=0, max_value=5000, places=2))
def test_the_cap_never_exceeds_the_optimistic_bound(area: Decimal) -> None:
    band = kwp_band(area, A)
    cap = roof_max_kwp(area, A)
    assert cap <= band.hi
    # Quantised DOWN, so the cap can sit a hair under the band's low bound but
    # never above it.
    assert cap <= band.lo


@given(
    smaller=st.decimals(min_value=0, max_value=2000, places=2),
    extra=st.decimals(min_value=0, max_value=2000, places=2),
)
def test_more_usable_roof_never_supports_less(smaller: Decimal, extra: Decimal) -> None:
    """Monotonic. A user correcting the area upward must never see the roof
    maximum fall."""
    assert roof_max_kwp(smaller + extra, A) >= roof_max_kwp(smaller, A)


def test_the_area_band_comes_from_the_versioned_pack_not_the_code() -> None:
    """NFR-4: nothing regulatory or assumed is hardcoded. If this conversion ever
    moves into a literal in capacity.py, this test is what notices."""
    assert A.area_per_kwp_m2.lo > 0
    assert A.area_per_kwp_m2.hi > A.area_per_kwp_m2.lo
    assert not A.is_verified, (
        "the pack is still UNVERIFIED_AGAINST_PRIMARY_SOURCE; if that changed, "
        "someone should have measured real module dimensions and an array layout"
    )
