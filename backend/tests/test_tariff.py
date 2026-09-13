"""Tariff engine unit tests, driven by the worked examples in the PRD itself."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from pvmaps.tariff import (
    Slab,
    TariffSchedule,
    bill_amount,
    load_schedule,
    marginal_rate,
    slab_descent,
    solar_savings,
)

TN = load_schedule("tn-domestic-2025-07-01")

# PRD 8.1 / 7 item 2: published inland-TN specific yield band.
YIELD_KWH_PER_KWP_YR = Decimal(1500)


def D(x: str | int) -> Decimal:
    return Decimal(str(x))


# --------------------------------------------------------------------------
# PRD 1.2 -- the worked example the whole product is argued from
# --------------------------------------------------------------------------


def test_prd_worked_example_450_units() -> None:
    """0 free + 470 + 630 + 840 + 577.50 = Rs 2517.50."""
    assert bill_amount(450, TN) == D("2517.50")


def test_slab_descent_is_top_down_and_conserves_units() -> None:
    """Solar eats from the top slab downward -- FR-4.1."""
    blocks = slab_descent(450, TN)
    assert [(b.kwh, b.rate) for b in blocks] == [
        (D(50), D("11.55")),
        (D(100), D("8.40")),
        (D(100), D("6.30")),
        (D(100), D("4.70")),
        (D(100), D("0.00")),
    ]
    assert sum(b.kwh for b in blocks) == D(450)


@pytest.mark.parametrize(
    ("units", "expected"),
    [
        (0, "0.00"),
        (95, "0.00"),     # PRD 1.2: the household that saves nothing
        (100, "0.00"),    # the 100th unit is still free
        (101, "4.70"),
        (200, "4.70"),
        (201, "6.30"),
        (400, "8.40"),
        (401, "11.55"),
        (450, "11.55"),   # PRD 1.2: the neighbour
        (2000, "11.55"),
    ],
)
def test_marginal_rate(units: int, expected: str) -> None:
    """The rate the LAST unit consumed is billed at -- the one solar displaces."""
    assert marginal_rate(units, TN) == D(expected)


# --------------------------------------------------------------------------
# PRD G2 -- the honest zero
# --------------------------------------------------------------------------


def test_free_slab_household_saves_exactly_zero() -> None:
    """PRD 1.2: 'A household at 95 units/month saves Rs 0.'

    Not 'nearly zero'. Not 'a small amount'. Zero. Any calculator that
    multiplies by an average tariff also returns zero here, so this is the one
    case where the market happens to be right -- and it is still the case the
    market never shows anyone.
    """
    r = solar_savings(units=95, solar_kwh=95, schedule=TN)
    assert r.savings == Decimal(0)
    assert r.is_worthless
    assert r.effective_rate == Decimal(0)


def test_zero_is_not_reached_by_rounding() -> None:
    """A household just over the free allowance saves a real, small amount."""
    r = solar_savings(units=101, solar_kwh=1, schedule=TN)
    assert r.savings == D("4.70")
    assert not r.is_worthless


# --------------------------------------------------------------------------
# PRD 1.2 -- why every calculator in the market is wrong
# --------------------------------------------------------------------------


def test_average_tariff_understates_a_high_consumer_by_a_third() -> None:
    """'Every calculator in the market multiplies kWh x average tariff and is
    therefore wrong by up to 100% in both directions.'

    565 units/month, 375 kWh/month of solar (a 3 kWp system at 1500 kWh/kWp/yr):
        marginal, top-down : Rs 3422.75
        average tariff     : Rs 2552.49
    The market's method loses a quarter of the value. Understating is the
    failure mode that keeps a household who SHOULD install from installing.
    """
    units, solar = D(565), D(375)

    true_savings = solar_savings(units, solar, TN).savings
    average_tariff = bill_amount(units, TN) / units
    naive_savings = solar * average_tariff

    assert true_savings == D("3422.75")
    assert true_savings > naive_savings * D("1.3")


def test_average_tariff_never_overstates_a_correctly_sized_system() -> None:
    """The PRD says the market's method is 'wrong by up to 100% in BOTH
    directions'. That is true, but not for the reason it reads like.

    For any telescopic tariff, valuing the top-down descent of S <= U kWh
    always meets or beats the average-tariff method, because the top slabs
    carry the highest rates and the descent eats them first. The average is a
    mean over the whole stack; the descent is a mean over its most expensive
    part.

    So a correctly sized system can only ever be UNDERvalued by the market's
    arithmetic. Verified exhaustively over the plausible domain below -- if
    this ever fails, the schedule has a non-monotonic rate and the descent
    logic needs revisiting.
    """
    for u in (Decimal(x) for x in range(50, 901, 50)):
        for s in (Decimal(x) for x in range(25, 901, 25)):
            if s > u:
                continue
            true_savings = solar_savings(u, s, TN).savings
            naive_savings = s * (bill_amount(u, TN) / u)
            assert naive_savings <= true_savings, f"overstated at U={u}, S={s}"


def test_average_tariff_overstates_only_via_export() -> None:
    """The other direction, and it comes from oversizing -- not low consumption.

    The average-tariff method multiplies EVERY generated unit by a retail
    average, including the ones that leave the house. Export earns a separate
    net-metering rate, not the retail average, so the moment a system generates
    more than the household consumes the market's arithmetic inflates.

    This is the failure mode that sells someone twice the system they need.
    """
    units, solar = D(200), D(500)

    true_savings = solar_savings(units, solar, TN).savings
    naive_savings = solar * (bill_amount(units, TN) / units)

    assert true_savings == D("470.00")          # the 100 billable units only
    assert naive_savings > true_savings * D(2)  # Rs 1175 vs Rs 470


# --------------------------------------------------------------------------
# PRD 11 beat 2 -- pinning down the demo script's own numbers
# --------------------------------------------------------------------------


def test_demo_beat_2_neighbour_consumption_is_about_565_units() -> None:
    """PRD 11: 'the same 3 kW on your neighbour's meter is worth Rs 41,000/year.'

    The PRD never says what that neighbour consumes. This test derives it, so
    the demo script is internally consistent when a judge asks.

        3 kWp x 1500 kWh/kWp/yr = 4500 kWh/yr = 375 kWh/month
        565 units/month -> Rs 3422.75/month -> Rs 41,073/year

    Worth knowing: the 450-unit household from PRD 1.2 is a DIFFERENT example
    and cannot reach Rs 41,000. Its entire annual bill is only Rs 30,210, so
    Rs 41,000 of savings is arithmetically impossible there. Do not merge the
    two examples on stage.
    """
    monthly_solar = (D(3) * YIELD_KWH_PER_KWP_YR) / D(12)
    assert monthly_solar == D(375)

    annual = solar_savings(D(565), monthly_solar, TN).savings * D(12)
    assert D(40_500) < annual < D(41_500), annual

    ceiling_at_450 = bill_amount(450, TN) * D(12)
    assert ceiling_at_450 < D(41_000)


# --------------------------------------------------------------------------
# Export -- the overclaim this codebase exists to avoid
# --------------------------------------------------------------------------


def test_generation_beyond_consumption_is_not_valued() -> None:
    """Export is compensated at a net-metering rate, not a slab rate.

    Valuing exported units at Rs 11.55 would inflate every oversized system on
    the map. PRD 10: 'Never fabricate a precise number.'
    """
    r = solar_savings(units=200, solar_kwh=500, schedule=TN)
    assert r.offset_kwh == D(200)
    assert r.exported_kwh == D(300)
    assert r.savings == D("470.00")     # the 100 billable units only


def test_effective_rate_is_below_the_marginal_rate_for_a_large_system() -> None:
    """A system big enough to eat into lower slabs realises less per kWh than
    its top-slab rate. This is why sizing matters and why the map cannot just
    show 'max kWp'."""
    r = solar_savings(units=565, solar_kwh=375, schedule=TN)
    assert r.effective_rate < marginal_rate(565, TN)
    assert r.effective_rate == D("9.13")


# --------------------------------------------------------------------------
# Schedule integrity -- NFR-4
# --------------------------------------------------------------------------


def test_rates_are_decimal_not_float() -> None:
    """PRD 8.1 requires rupee-exact output. A float anywhere in the chain
    forfeits that."""
    assert all(isinstance(s.rate, Decimal) for s in TN.slabs)
    assert isinstance(bill_amount(450, TN), Decimal)


def test_a_gap_between_slabs_is_rejected() -> None:
    """A silent gap under-bills every consumer above it."""
    with pytest.raises(ValueError, match="not contiguous"):
        TariffSchedule(
            version="broken",
            effective_from=date(2025, 7, 1),
            category="DOMESTIC",
            currency="INR",
            billing_period_months=1,
            slabs=(
                Slab(0, 100, D(0)),
                Slab(150, None, D(5)),   # 101-150 falls through the floor
            ),
            source="",
            verification_status="",
        )


def test_a_bounded_top_slab_is_rejected() -> None:
    """High consumers must not fall off the end of the schedule."""
    with pytest.raises(ValueError, match="unbounded"):
        TariffSchedule(
            version="broken",
            effective_from=date(2025, 7, 1),
            category="DOMESTIC",
            currency="INR",
            billing_period_months=1,
            slabs=(Slab(0, 100, D(0)),),
            source="",
            verification_status="",
        )


def test_bimonthly_conversion_refuses_to_guess() -> None:
    """The bimonthly cycle is unresolved; the code must not paper over it.

    Asserts on the refusal itself rather than on a PRD section number, so that
    renumbering the document cannot turn a real guard into a red test.
    """
    with pytest.raises(NotImplementedError, match=r"bimonthly slab boundaries are unverified"):
        TN.to_billing_period(2)


def test_negative_consumption_is_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        bill_amount(-1, TN)
