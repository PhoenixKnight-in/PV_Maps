"""Bill field extraction — FR-3.4, and the bimonthly refusal.

    "Use OCR only to copy visible fields. The user must be able to correct every
     extracted value before calculation."

The tests that matter most here are the ones asserting that nothing is produced:
a parser that guesses a sanctioned load is worse than one that fails, because the
guess arrives pre-filled in the form and looking like it came off the bill.

No fixture here is a real bill. Real bills carry a consumer number and a name
(NFR-1), and none is needed to test a regex.
"""

from __future__ import annotations

from decimal import Decimal

from pvmaps.api.bill_parse import parse_bill_text

MONTHLY = """
TANGEDCO / TNPDCL  ELECTRICITY BILL
Tariff : LT-IA          Single Phase
Sanctioned Load : 3 KW
Service Period From 01/07/2025 To 31/07/2025
Units Consumed : 565
Energy Charges  2517.50
"""

BIMONTHLY = MONTHLY.replace("To 31/07/2025", "To 31/08/2025")


def test_a_monthly_bill_fills_the_monthly_field() -> None:
    f = parse_bill_text(MONTHLY)
    assert f.billed_units_kwh == Decimal(565)
    assert f.billing_period_days == 30
    assert f.billing_period_months == 1
    assert f.monthly_units_kwh == Decimal(565)
    assert f.sanctioned_load_kw == Decimal(3)
    assert f.tariff_category == "LT-IA"
    assert f.phase == "SINGLE"
    assert f.warnings == ()


def test_a_bimonthly_bill_refuses_to_fill_the_monthly_field() -> None:
    """PRD 8.2. Neither available move is safe: 1130 units in a field labelled
    "per month" doubles the household's consumption, and halving it applies
    exactly the linear scaling `to_billing_period` refuses to perform. So the
    parser reports the billed figure and the period, and asks."""
    f = parse_bill_text(BIMONTHLY)
    assert f.billed_units_kwh == Decimal(565)
    assert f.billing_period_days == 61
    assert f.billing_period_months == 2
    assert f.monthly_units_kwh is None

    patch = f.to_form_patch()
    assert "monthly_units_kwh" not in patch
    assert patch["billed_units_kwh"] == 565.0
    assert any("ONE month" in w for w in patch["warnings"])


def test_an_unreadable_period_also_refuses_the_monthly_field() -> None:
    """TNPDCL bills bimonthly by default, so "we could not tell" must not resolve
    to "assume monthly"."""
    f = parse_bill_text("Units Consumed : 565\nSanctioned Load : 3 KW")
    assert f.billed_units_kwh == Decimal(565)
    assert f.monthly_units_kwh is None
    assert any("one month or two" in w for w in f.warnings)


def test_nothing_found_means_nothing_returned() -> None:
    patch = parse_bill_text("this is a shopping list, not a bill").to_form_patch()
    assert patch["extracted_fields"] == []
    assert "monthly_units_kwh" not in patch
    assert "sanctioned_load_kw" not in patch
    assert len(patch["warnings"]) == 2


def test_a_missing_sanctioned_load_says_it_will_not_be_guessed() -> None:
    """PRD 1.1 constraint #2. It caps the plant size, so a default here would
    fabricate the exact number the product exists to surface."""
    f = parse_bill_text("Units Consumed : 565\nFrom 01/07/2025 To 31/07/2025")
    assert f.sanctioned_load_kw is None
    assert any("not something we will guess" in w for w in f.warnings)


def test_a_kva_sanctioned_figure_is_flagged_not_silently_treated_as_kw() -> None:
    f = parse_bill_text("Sanctioned Demand : 5 KVA\nUnits Consumed : 400")
    assert f.sanctioned_load_kw == Decimal(5)
    assert any("kVA" in w for w in f.warnings)


def test_a_load_stated_in_watts_is_converted_because_the_bill_said_watts() -> None:
    """A conversion the bill itself licenses. 3000 W is 3 kW by definition, which
    is different in kind from inferring a value nobody wrote down."""
    f = parse_bill_text("Sanctioned Load : 3000 W\nUnits Consumed : 400")
    assert f.sanctioned_load_kw == Decimal(3)


def test_a_thousands_separator_parses() -> None:
    f = parse_bill_text("Units Consumed : 1,130\nFrom 01/07/2025 To 31/07/2025")
    assert f.billed_units_kwh == Decimal(1130)


def test_an_impossible_date_is_discarded_not_crashed_on() -> None:
    f = parse_bill_text("From 31/02/2025 To 31/07/2025\nUnits Consumed : 400")
    assert f.billing_period_days is None  # only one valid date survived


def test_a_span_too_long_to_be_a_service_period_is_ignored() -> None:
    """Bills carry other dates — a connection date, a meter-change date. A
    two-year span is not a billing period and must not be treated as one."""
    f = parse_bill_text("Connected 01/01/2020\nBill Date 01/07/2025\nUnits Consumed : 400")
    assert f.billing_period_days is None
    assert f.monthly_units_kwh is None


def test_alternative_units_labels_are_recognised() -> None:
    for label in ("No. of Units", "Net Units", "Total Units", "Consumption in Units"):
        f = parse_bill_text(f"{label} : 450\nFrom 01/07/2025 To 31/07/2025")
        assert f.billed_units_kwh == Decimal(450), label


def test_three_phase_is_recognised_in_both_spellings() -> None:
    assert parse_bill_text("Three Phase service").phase == "THREE"
    assert parse_bill_text("3-Ph supply").phase == "THREE"
    assert parse_bill_text("1 Phase supply").phase == "SINGLE"


def test_the_patch_always_demands_human_confirmation() -> None:
    """FR-3.4. The flag travels in the payload so a consumer that is not our own
    browser cannot miss the requirement."""
    assert parse_bill_text(MONTHLY).to_form_patch()["must_confirm"] is True
    assert parse_bill_text("").to_form_patch()["must_confirm"] is True
