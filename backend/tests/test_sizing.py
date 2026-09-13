"""Sizing optimiser tests — ARCHITECTURE.md 10 item 2:

    "Build the pure sizing optimiser and test its roof/sanctioned-load
     invariants."

The band invariants matter as much as the roof ones. An inverted or overstated
range is not a cosmetic defect here: ARCHITECTURE.md 7 says the API "must never
represent a self-consumption estimate as an observed fact", and a band that is
wrong in the narrow direction does exactly that.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pvmaps.sizing import (
    KWP_STEP,
    Occupancy,
    Range,
    UsageModifier,
    UsageProfile,
    Verdict,
    load_assumptions,
    load_subsidy,
    optimise,
    split_generation,
)
from pvmaps.tariff import load_schedule

TN = load_schedule("tn-domestic-2025-07-01")
A = load_assumptions()
S = load_subsidy()


def D(x: str | int) -> Decimal:
    return Decimal(str(x))


def profile(units: int, occ: Occupancy = Occupancy.PARTIAL, sl: int | str = 3) -> UsageProfile:
    return UsageProfile(
        monthly_units_kwh=D(units), occupancy=occ, sanctioned_load_kw=D(sl)
    )


# --------------------------------------------------------------------------
# Roof and sanctioned-load invariants
# --------------------------------------------------------------------------


def test_sanctioned_load_caps_a_generous_roof() -> None:
    """PRD 11 beat 1. The roof says 6.5 kWp; the contract says 3 kW.

    "Your roof was never the limit."
    """
    r = optimise(profile(565, sl=3), roof_max_kwp=D("6.5"), tariff=TN)

    assert r.feasible_max_kwp == D(3)
    assert r.binding_constraint == "SANCTIONED_LOAD"
    assert r.recommended is not None
    assert r.recommended.kwp <= D(3)


def test_roof_caps_a_generous_sanctioned_load() -> None:
    r = optimise(profile(565, sl=10), roof_max_kwp=D("2.5"), tariff=TN)

    assert r.feasible_max_kwp == D("2.5")
    assert r.binding_constraint == "ROOF"


def test_no_installable_size_is_reported_not_rounded_up() -> None:
    """A 0.4 kW ceiling must yield NO_CAPACITY, never a 0.5 kW recommendation
    that dies at feasibility review."""
    r = optimise(profile(565, sl="0.4"), roof_max_kwp=D(10), tariff=TN)

    assert r.verdict is Verdict.NO_CAPACITY
    assert r.recommended is None
    assert r.curve == ()


@given(
    units=st.integers(0, 1500),
    roof_steps=st.integers(0, 40),
    sl_steps=st.integers(1, 40),
    occ=st.sampled_from(list(Occupancy)),
)
@settings(max_examples=200, deadline=None)
def test_recommendation_never_exceeds_either_ceiling(
    units: int, roof_steps: int, sl_steps: int, occ: Occupancy
) -> None:
    """The hard constraint. Exceeding it means telling a household their
    application will be approved when the DISCOM will reject it."""
    roof = D(roof_steps) * KWP_STEP
    sl = D(sl_steps) * KWP_STEP
    r = optimise(profile(units, occ, sl=sl), roof_max_kwp=roof, tariff=TN)  # type: ignore[arg-type]

    assert r.feasible_max_kwp <= roof
    assert r.feasible_max_kwp <= sl
    for c in r.curve:
        assert c.kwp <= roof
        assert c.kwp <= sl
        assert (c.kwp / KWP_STEP) % 1 == 0, "not an installable size"
    if r.recommended is not None:
        assert r.recommended.kwp <= r.feasible_max_kwp


# --------------------------------------------------------------------------
# Band invariants -- the class of bug that inverted export
# --------------------------------------------------------------------------


@given(
    units=st.integers(0, 1500),
    kwp_steps=st.integers(1, 40),
    occ=st.sampled_from(list(Occupancy)),
    mods=st.sets(st.sampled_from([UsageModifier.DAYTIME_AC_PLANNED,
                                  UsageModifier.EV_CHARGED_AT_NIGHT]), max_size=2),
)
@settings(max_examples=300, deadline=None)
def test_energy_split_bands_are_never_inverted_or_negative(
    units: int, kwp_steps: int, occ: Occupancy, mods: set[UsageModifier]
) -> None:
    """Every band satisfies lo <= hi and lo >= 0, and self-consumption never
    exceeds generation.

    Export and headroom are differences, so their bounds must CROSS. Pairing
    them elementwise produced an inverted interval that Range caught at
    construction -- this test is what keeps it caught.
    """
    p = UsageProfile(
        monthly_units_kwh=D(units),
        occupancy=occ,
        sanctioned_load_kw=D(10),
        modifiers=frozenset(mods),
    )
    split = split_generation(D(kwp_steps) * KWP_STEP, p, A)

    for name in ("generation", "self_consumed", "exported", "servable_headroom"):
        band: Range = getattr(split, name)
        assert band.lo <= band.hi, f"{name} inverted"
        assert band.lo >= 0, f"{name} negative"

    assert split.self_consumed.lo <= split.generation.hi
    assert split.self_consumed.hi <= split.generation.hi

    # A system cannot both export and leave headroom in the same world.
    assert not (split.exported.lo > 0 and split.servable_headroom.lo > 0)


def test_export_is_bounded_by_the_widest_true_pairing() -> None:
    """Most export = highest generation against lowest servable load.
    Least export = the reverse. Anything narrower is an overclaim."""
    p = profile(200, Occupancy.EMPTY_WEEKDAYS, sl=10)   # servable 0.10-0.25
    split = split_generation(D(5), p, A)                 # heavily oversized

    servable = Range.exact(D(200)) * p.servable_fraction(A)
    assert split.exported.lo == max(Decimal(0), split.generation.lo - servable.hi)
    assert split.exported.hi == max(Decimal(0), split.generation.hi - servable.lo)
    assert split.is_saturated


def test_a_wider_servable_band_never_narrows_the_export_band() -> None:
    """Monotonicity check on uncertainty: less knowledge must not produce a
    more confident answer."""
    narrow = profile(400, Occupancy.PARTIAL, sl=10)          # 0.25-0.45
    wide = UsageProfile(
        monthly_units_kwh=D(400),
        occupancy=Occupancy.PARTIAL,
        sanctioned_load_kw=D(10),
        modifiers=frozenset({UsageModifier.DAYTIME_AC_PLANNED}),  # widens
    )
    assert wide.servable_fraction(A).width >= narrow.servable_fraction(A).width


# --------------------------------------------------------------------------
# The honest zero -- PRD G2
# --------------------------------------------------------------------------


def test_free_slab_household_gets_no_recommendation() -> None:
    """PRD 1.2: at 95 units/month solar displaces only free units.

    PRD 10: the UI must never let this sit alone. That is a rendering
    requirement, but it starts here -- the engine has to be willing to say no.
    """
    r = optimise(profile(95, Occupancy.HOME_ALL_DAY, sl=3), roof_max_kwp=D("6.5"), tariff=TN)

    assert r.verdict is Verdict.NOT_ECONOMIC
    assert r.recommended is None
    assert r.curve, "the curve is still returned so the UI can show why"
    assert all(c.annual_bill_savings.hi == 0 for c in r.curve)


def test_a_high_slab_household_is_recommended_something() -> None:
    r = optimise(profile(565, Occupancy.HOME_ALL_DAY, sl=5), roof_max_kwp=D("6.5"), tariff=TN)

    assert r.verdict is Verdict.RECOMMENDED
    assert r.recommended is not None
    assert r.recommended.annual_bill_savings.lo > 0


# --------------------------------------------------------------------------
# Why bigger is not better
# --------------------------------------------------------------------------


def test_savings_are_monotonic_but_effective_rate_decays() -> None:
    """More panels never save less, but each additional panel saves less than
    the last once the household's daytime load is saturated. That decay is the
    entire argument for recommending a size below the roof maximum."""
    r = optimise(profile(565, Occupancy.PARTIAL, sl=10), roof_max_kwp=D(10), tariff=TN)

    savings = [c.annual_bill_savings.lo for c in r.curve]
    assert savings == sorted(savings), "savings must never decrease with size"

    rates = [c.effective_rate.lo for c in r.curve]
    assert rates[-1] < rates[0], "effective rate must decay as the system saturates"


def test_recommendation_is_capped_below_the_physical_maximum() -> None:
    """The economic optimum, not the roof maximum. This is the claim that a
    max-out-your-roof calculator cannot make."""
    r = optimise(profile(565, Occupancy.PARTIAL, sl=10), roof_max_kwp=D(10), tariff=TN)

    assert r.recommended is not None
    assert r.recommended.kwp < r.feasible_max_kwp
    assert r.is_economically_capped


def test_export_is_not_valued_until_a_rate_is_sourced() -> None:
    """The export band is pinned at zero in config until the primary TN
    net-metering order is read. Any credit appearing here is an overclaim."""
    assert not A.values_export
    r = optimise(profile(200, Occupancy.EMPTY_WEEKDAYS, sl=10), roof_max_kwp=D(10), tariff=TN)
    assert all(c.annual_export_credit.hi == 0 for c in r.curve)


# --------------------------------------------------------------------------
# Subsidy
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwp", "expected"),
    [
        ("0", "0"),
        ("1", "30000"),
        ("2", "60000"),
        ("3", "78000"),      # 2 x 30000 + 1 x 18000, then the cap
        ("5", "78000"),      # cap binds
        ("50", "78000"),     # above eligibility, capped not scaled
    ],
)
def test_subsidy_tiers_are_marginal_and_capped(kwp: str, expected: str) -> None:
    assert S.amount_for(D(kwp)) == D(expected)


@given(a=st.integers(0, 200), b=st.integers(0, 200))
@settings(max_examples=100, deadline=None)
def test_subsidy_is_monotonic_in_system_size(a: int, b: int) -> None:
    """A bigger system must never attract less subsidy -- that would create a
    perverse incentive in the optimiser."""
    lo, hi = sorted((D(a) * KWP_STEP, D(b) * KWP_STEP))
    assert S.amount_for(lo) <= S.amount_for(hi)


# --------------------------------------------------------------------------
# Range arithmetic
# --------------------------------------------------------------------------


def test_subtraction_crosses_its_bounds() -> None:
    """The rule the export bug violated."""
    assert Range.of(10, 20) - Range.of(3, 5) == Range.of(5, 17)


def test_inverted_range_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="inverted"):
        Range.of(10, 5)


def test_division_by_a_range_spanning_zero_is_rejected() -> None:
    with pytest.raises(ZeroDivisionError, match="spans zero"):
        Range.of(1, 2) / Range.of(-1, 1)


def test_multiplication_considers_all_four_corners() -> None:
    assert Range.of(-2, 3) * Range.of(-4, 5) == Range.of(-12, 15)


def test_estimate_conversion_uses_the_midpoint_not_the_optimistic_bound() -> None:
    """NFR-2 / ARCHITECTURE.md 7: crossing into the API layer must not quietly
    promote the best case to the headline number."""
    est = Range.of(100, 200).to_estimate(source="inferred", confidence=0.5)
    assert est.value == 150.0
    assert (est.lo, est.hi) == (100.0, 200.0)
    assert not est.is_certain


# --------------------------------------------------------------------------
# Profile validation
# --------------------------------------------------------------------------


def test_missing_sanctioned_load_is_not_defaulted() -> None:
    """It is a hard cap. A silent default would fabricate the exact number
    demo beat 1 is about."""
    with pytest.raises(ValueError, match="sanctioned load"):
        UsageProfile(monthly_units_kwh=D(400), occupancy=Occupancy.PARTIAL,
                     sanctioned_load_kw=D(0))


def test_contradictory_ev_modifiers_are_rejected() -> None:
    with pytest.raises(ValueError, match="EV"):
        UsageProfile(
            monthly_units_kwh=D(400),
            occupancy=Occupancy.PARTIAL,
            sanctioned_load_kw=D(3),
            modifiers=frozenset({UsageModifier.EV_CHARGED_AT_NIGHT,
                                 UsageModifier.EV_CHARGED_BY_DAY}),
        )


def test_servable_fraction_is_clamped_to_configured_bounds() -> None:
    p = UsageProfile(
        monthly_units_kwh=D(400),
        occupancy=Occupancy.EMPTY_WEEKDAYS,
        sanctioned_load_kw=D(3),
        modifiers=frozenset({UsageModifier.EV_CHARGED_AT_NIGHT}),  # pushes down
    )
    band = p.servable_fraction(A)
    assert band.lo >= A.servable_floor
    assert band.hi <= A.servable_ceiling


def test_assumption_packs_are_flagged_unverified() -> None:
    """Both packs carry secondary-source numbers. Until they are checked, the
    recommendation must announce that it is provisional."""
    r = optimise(profile(565, sl=3), roof_max_kwp=D("6.5"), tariff=TN)
    assert not r.assumptions_verified
