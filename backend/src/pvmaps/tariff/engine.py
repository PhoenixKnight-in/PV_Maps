"""Telescopic slab descent — PRD FR-4.1.

    "Solar displaces consumption from the top slab downward, so the correct
     valuation is the MARGINAL slab rate, not the average tariff."

    "Every calculator in the market multiplies kWh x average tariff and is
     therefore wrong by up to 100% in both directions."

This module is the reason the product is not a calculator. It is pure: no
database, no HTTP, no clock. Everything is Decimal.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from pvmaps.tariff.schedule import TariffSchedule, slab_label

__all__ = [
    "Block",
    "SavingsResult",
    "bill_amount",
    "bill_amount_rupees",
    "marginal_rate",
    "slab_descent",
    "solar_savings",
]

_PAISE = Decimal("0.01")
_RUPEE = Decimal("1")
_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class Block:
    """A contiguous run of kWh billed at one rate."""

    kwh: Decimal
    rate: Decimal
    slab_from: int
    slab_to: int | None

    @property
    def amount(self) -> Decimal:
        return self.kwh * self.rate

    @property
    def label(self) -> str:
        return slab_label(self.slab_from, self.slab_to)


def _d(x: Decimal | int | float | str) -> Decimal:
    # float goes through str so binary representation error never enters the sum.
    return x if isinstance(x, Decimal) else Decimal(str(x))


def bill_amount(units: Decimal | int | float, schedule: TariffSchedule) -> Decimal:
    """Total telescopic bill for `units` consumed in one billing period.

    Exact, unrounded. Worked against the dated tariff pack
    (monthly-equivalent, 2025-07-01):
    450 units -> 0 + 470.00 + 630.00 + 840.00 + 577.50 = Rs 2517.50
    """
    u = _d(units)
    if u < _ZERO:
        raise ValueError(f"consumption cannot be negative: {u}")
    return sum((s.units_in(u) * s.rate for s in schedule.slabs), start=_ZERO)


def bill_amount_rupees(units: Decimal | int | float, schedule: TariffSchedule) -> Decimal:
    """`bill_amount` rounded half-up to the rupee.

    PRD 10 (acceptance criteria) acceptance is stated "to the rupee". Which rounding TNPDCL
    actually applies -- and whether it rounds the total or each component -- is
    unconfirmed; tests/test_tariff_golden.py is what settles it against real
    bills. Do not tune this function to make a test pass; tune it to match a
    bill you are holding.
    """
    return bill_amount(units, schedule).quantize(_RUPEE, rounding=ROUND_HALF_UP)


def marginal_rate(units: Decimal | int | float, schedule: TariffSchedule) -> Decimal:
    """Rs/kWh at which the LAST unit consumed is billed.

    That is the first unit solar displaces, so this is the marginal rate in the
    sense FR-4.1 means it.

    This is the number the entire product turns on. PRD 2.2, worked against
    the 2025-07-01 pack:
    a household at 95 units/month has a marginal rate of Rs 0.00; their
    neighbour at 450 units/month has Rs 11.55. Same roof, same sun.
    """
    return schedule.slab_for(_d(units)).rate


def slab_descent(units: Decimal | int | float, schedule: TariffSchedule) -> tuple[Block, ...]:
    """The consumption stack, TOP SLAB FIRST — the order solar eats it in.

    For 450 units on the 2025-07-01 schedule:
        [ (50 kWh @ 11.55), (100 @ 8.40), (100 @ 6.30), (100 @ 4.70), (100 @ 0.00) ]
    """
    u = _d(units)
    if u < _ZERO:
        raise ValueError(f"consumption cannot be negative: {u}")
    blocks = [
        Block(kwh=k, rate=s.rate, slab_from=s.slab_from, slab_to=s.slab_to)
        for s in schedule.slabs
        if (k := s.units_in(u)) > _ZERO
    ]
    return tuple(reversed(blocks))


@dataclass(frozen=True, slots=True)
class SavingsResult:
    units: Decimal
    """Consumption in the billing period, kWh."""

    solar_kwh: Decimal
    """Generation offered against that consumption, kWh."""

    offset_kwh: Decimal
    """Generation that actually displaced a billed unit."""

    exported_kwh: Decimal
    """Generation beyond consumption. NOT valued here -- see note below."""

    savings: Decimal
    """Rupees saved in the billing period. Exact, unrounded."""

    blocks: tuple[Block, ...]
    """The descent that was consumed, top-down. For the UI waterfall (FR-4.3)."""

    @property
    def effective_rate(self) -> Decimal:
        """Rs/kWh actually realised. Zero when nothing was displaced.

        Compare against the average tariff to show how wrong the market's
        arithmetic is for this consumer (PRD 2.2).
        """
        if self.offset_kwh <= _ZERO:
            return _ZERO
        return (self.savings / self.offset_kwh).quantize(_PAISE, rounding=ROUND_HALF_UP)

    @property
    def is_worthless(self) -> bool:
        """The honest zero. PRD G2, and demo beat 2.

        PRD 10: never let this sit alone in the UI. Always pair it with the
        neighbour's number. The verb is *route*, never *reject*.
        """
        return self.savings <= _ZERO


def solar_savings(
    units: Decimal | int | float,
    solar_kwh: Decimal | int | float,
    schedule: TariffSchedule,
) -> SavingsResult:
    """Value `solar_kwh` of generation against `units` of consumption.

    Eats the slab descent from the top down. This is FR-4.1 in eight lines, and
    it is the whole difference between this product and every calculator in the
    market.

    Export beyond consumption is deliberately valued at zero. Net-metering
    export compensation is a separate rate, not a slab rate, and quietly
    valuing exported units at Rs 11.55 would be exactly the overclaim this
    codebase exists to avoid. `exported_kwh` is surfaced so the UI can say so.
    """
    u, s = _d(units), _d(solar_kwh)
    if s < _ZERO:
        raise ValueError(f"generation cannot be negative: {s}")

    remaining = s
    total = _ZERO
    consumed: list[Block] = []

    for block in slab_descent(u, schedule):
        if remaining <= _ZERO:
            break
        take = min(remaining, block.kwh)
        total += take * block.rate
        consumed.append(
            Block(kwh=take, rate=block.rate, slab_from=block.slab_from, slab_to=block.slab_to)
        )
        remaining -= take

    offset = s - remaining
    return SavingsResult(
        units=u,
        solar_kwh=s,
        offset_kwh=offset,
        exported_kwh=remaining,
        savings=total,
        blocks=tuple(consumed),
    )
