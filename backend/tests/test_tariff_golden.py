"""Golden test — PRD 8.1's most falsifiable acceptance criterion.

    "Tariff engine | Computed bill matches 5 real TANGEDCO bills TO THE RUPEE
     -- most falsifiable component, must be exact."

THIS TEST IS EXPECTED TO FAIL ON A FRESH CLONE. That is the point.

Every other component in this system degrades gracefully when it is wrong: a
roof outline can be a little off, a DT quota carries a confidence band. The
tariff engine cannot. It is checkable by anyone holding a paper bill and a
phone, and it is the single number the entire valuation rests on. So it gets a
test that stays red until it has been checked against reality.

To make it pass: fill in tests/fixtures/bills/real_bills.json. Read that file's
_README first -- in particular the PII rules (NFR-1) and the bimonthly problem
(PRD 8.2).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from pvmaps.tariff import bill_amount, bill_amount_rupees, load_schedule

FIXTURE = Path(__file__).parent / "fixtures" / "bills" / "real_bills.json"
REQUIRED_BILLS = 5


def _load() -> tuple[str, list[dict]]:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    bills = [b for b in raw["bills"] if b.get("units_kwh") is not None]
    return raw["schedule_version"], bills


def test_five_real_bills_are_present() -> None:
    """Gate. Until this passes, the tariff engine is unvalidated."""
    _version, bills = _load()
    if len(bills) < REQUIRED_BILLS:
        pytest.fail(
            f"\n"
            f"  PRD 8.1 requires {REQUIRED_BILLS} real TANGEDCO bills; found {len(bills)}.\n"
            f"  Fill in: {FIXTURE}\n"
            f"\n"
            f"  This failure is deliberate. The tariff engine is the highest\n"
            f"  value-per-hour item in the build (PRD 7 item 3) and the only\n"
            f"  component a judge can falsify from the audience. Do not delete\n"
            f"  this test; feed it.\n"
        )


def test_schedule_is_verified_against_primary_source() -> None:
    """PRD 8.2: the slab boundaries themselves are still unconfirmed.

    Separate from the bills. A schedule can be internally valid and still be
    the wrong schedule.
    """
    version, _ = _load()
    schedule = load_schedule(version)
    if not schedule.is_verified:
        pytest.fail(
            f"\n"
            f"  Schedule {schedule.version!r} is marked {schedule.verification_status!r}.\n"
            f"  Open items from PRD 8.2:\n"
            f"    - bimonthly vs monthly slab boundaries (TN bills bimonthly;\n"
            f"      free allowance 100 units, reportedly rising to 200 for\n"
            f"      consumers at or below 500 units bimonthly -- NOT a 2x scale)\n"
            f"  Read the primary TNERC order, then set verification_status to\n"
            f"  VERIFIED_AGAINST_PRIMARY_SOURCE in the schedule JSON.\n"
        )


def test_computed_bills_match_to_the_rupee() -> None:
    """The actual criterion. Reports every mismatch, not just the first."""
    version, bills = _load()
    if not bills:
        pytest.skip("no bills yet -- see test_five_real_bills_are_present")

    schedule = load_schedule(version)
    failures: list[str] = []

    for bill in bills:
        units = Decimal(str(bill["units_kwh"]))
        expected = Decimal(str(bill["energy_charge_inr"]))
        period = bill.get("billing_period_months")

        if period is not None and period != schedule.billing_period_months:
            failures.append(
                f"  {bill['label']}: bill covers {period} month(s) but schedule "
                f"{schedule.version!r} is {schedule.billing_period_months}-month. "
                f"PRD 8.2 -- do not compare these until the bimonthly schedule exists."
            )
            continue

        computed = bill_amount_rupees(units, schedule)
        if computed != expected:
            exact = bill_amount(units, schedule)
            failures.append(
                f"  {bill['label']}: {units} kWh -> computed Rs {computed} "
                f"(exact {exact}), bill says Rs {expected}, off by Rs {computed - expected}"
            )

    if failures:
        pytest.fail(
            "\n  Tariff engine does not match real bills to the rupee:\n"
            + "\n".join(failures)
            + "\n\n  Fix the SCHEDULE or the ENGINE to match the bill. Never the "
            "reverse.\n"
        )
