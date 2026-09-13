"""Read visible fields off a TNPDCL bill. Pure text in, candidate values out.

FR-3.4 is the whole design brief:

    "Use OCR only to copy visible fields. The user must be able to correct every
     extracted value before calculation."

So this module copies and never infers. It has no fallbacks, no defaults, and no
"typical" values: a field it cannot find is simply absent, and the browser's form
stays empty for the user to fill. An extractor that guesses a sanctioned load is
worse than one that fails, because the guess arrives pre-filled and looking
confident.

The one judgement call it does make is to REFUSE to convert a bimonthly bill to a
monthly figure — see `BillFields.monthly_units_kwh`.

Pure and dependency-free: no pypdf, no OCR engine, no network. That is what makes
it testable, and the text-extraction backends are kept in the route.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

__all__ = ["BillFields", "parse_bill_text"]

_NUM = r"([0-9]{1,6}(?:[.,][0-9]{1,3})?)"

_SANCTIONED_LOAD = re.compile(
    r"sanction(?:ed)?\s*(?:load|demand)\s*(?:\(?k[wv]a?\)?)?\s*[:\-=]?\s*" + _NUM,
    re.IGNORECASE,
)
_SANCTIONED_LOAD_UNIT = re.compile(
    r"sanction(?:ed)?\s*(?:load|demand)[^0-9]{0,20}[0-9.,]+\s*(kva|kw|w)\b",
    re.IGNORECASE,
)
_UNITS = re.compile(
    r"(?:units?\s*consumed|consumption\s*(?:in\s*)?units?|no\.?\s*of\s*units?"
    r"|net\s*units?|units?\s*billed|total\s*units?)\s*[:\-=]?\s*" + _NUM,
    re.IGNORECASE,
)
_TARIFF = re.compile(
    r"\b(?:tariff|category)\s*(?:code|category)?\s*[:\-=]?\s*"
    r"(LT\s*[-\s]?\s*[IV]+\s*[AB]?|HT\s*[-\s]?\s*[IV]+|[IV]+\s*[AB]?)\b",
    re.IGNORECASE,
)
_PHASE = re.compile(r"\b(?:(single|three)\s*phase|([13])\s*[-\s]?\s*ph(?:ase)?\b)", re.IGNORECASE)
_DATE = re.compile(r"\b([0-3]?[0-9])[/.\-]([01]?[0-9])[/.\-](20[0-9]{2})\b")

_MONTH_DAYS = 30.4
_MONTHLY_SPAN = range(20, 46)
"""A bill whose service period is 20-45 days is a one-month bill. Outside that
window no monthly figure is emitted -- see `BillFields.monthly_units_kwh`."""


def _decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


@dataclass(frozen=True, slots=True)
class BillFields:
    """What was visible on the bill. Every field is optional by design."""

    billed_units_kwh: Decimal | None = None
    """Units as the bill states them, for whatever period the bill covers."""

    billing_period_days: int | None = None
    billing_period_months: int | None = None
    period_from: date | None = None
    period_to: date | None = None

    sanctioned_load_kw: Decimal | None = None
    tariff_category: str | None = None
    phase: str | None = None

    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def monthly_units_kwh(self) -> Decimal | None:
        """Units for ONE month — only when the bill is positively a one-month bill.

        TNPDCL bills on a bimonthly cycle, and PRD 10 (must verify) records that the bimonthly
        free allowance is reported to be conditional rather than twice the
        monthly one. So neither available move is safe on a bimonthly bill:
        passing 1130 units into a field labelled "per month" doubles the
        household's consumption, and halving it to 565 applies exactly the linear
        scaling that `tariff.schedule.to_billing_period` refuses to perform.

        The honest third option is to return nothing and let the user answer. The
        billed figure and the detected period are still reported, so the UI can
        ask a specific question instead of a blank one.
        """
        if self.billed_units_kwh is None:
            return None
        if self.billing_period_days is None or self.billing_period_days not in _MONTHLY_SPAN:
            return None
        return self.billed_units_kwh

    def to_form_patch(self) -> dict[str, Any]:
        """The JSON the browser merges into its editable fields.

        Only keys that were actually found appear. A key present with a null
        value would clear a field the user had already typed into, and a key with
        a guessed value would arrive looking like it came off the bill.
        """
        patch: dict[str, Any] = {}
        if (monthly := self.monthly_units_kwh) is not None:
            patch["monthly_units_kwh"] = float(monthly)
        if self.sanctioned_load_kw is not None:
            patch["sanctioned_load_kw"] = float(self.sanctioned_load_kw)

        # Context, not form fields. The browser's Zod schema strips these; they
        # are here so a UI can show what the bill said and ask for a confirmation.
        if self.billed_units_kwh is not None:
            patch["billed_units_kwh"] = float(self.billed_units_kwh)
        if self.billing_period_days is not None:
            patch["billing_period_days"] = self.billing_period_days
        if self.billing_period_months is not None:
            patch["billing_period_months"] = self.billing_period_months
        if self.period_from is not None:
            patch["period_from"] = self.period_from.isoformat()
        if self.period_to is not None:
            patch["period_to"] = self.period_to.isoformat()
        if self.tariff_category is not None:
            patch["tariff_category"] = self.tariff_category
        if self.phase is not None:
            patch["phase"] = self.phase

        patch["extracted_fields"] = sorted(
            k for k in patch if k not in {"extracted_fields", "warnings"}
        )
        patch["warnings"] = list(self.warnings)
        # FR-3.4: nothing here may reach a calculation without a human
        # confirming it. The flag travels in the payload so a consumer that is
        # not our own browser cannot miss the requirement.
        patch["must_confirm"] = True
        return patch


def _find_period(text: str) -> tuple[date | None, date | None, int | None]:
    """Earliest and latest plausible dates on the bill, and the span between.

    Deliberately crude: bills place the service period in wildly different
    layouts, and the span between the first and last date on the page is a more
    robust signal than trying to recognise a label. Anything that does not look
    like a service period (a span over 120 days) is discarded rather than used.
    """
    found: list[date] = []
    for day, month, year in _DATE.findall(text):
        try:
            found.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue  # 31/02 and friends -- a misread, not a date
    if len(found) < 2:
        return (found[0] if found else None), None, None

    lo, hi = min(found), max(found)
    span = (hi - lo).days
    if not 1 <= span <= 120:
        return None, None, None
    return lo, hi, span


def parse_bill_text(text: str) -> BillFields:
    """Copy what is visible. Report what is missing as a warning, never a guess."""
    warnings: list[str] = []

    units = None
    if m := _UNITS.search(text):
        units = _decimal(m.group(1))
    if units is None:
        warnings.append("Could not find the units consumed — please enter them from your bill.")

    load = None
    if m := _SANCTIONED_LOAD.search(text):
        load = _decimal(m.group(1))
        unit_match = _SANCTIONED_LOAD_UNIT.search(text)
        unit = unit_match.group(1).lower() if unit_match else None
        if unit == "w" and load is not None and load > 1000:
            # A bill stating 3000 W means 3 kW. Stated, not inferred.
            load = load / Decimal(1000)
        elif unit == "kva":
            warnings.append(
                "The sanctioned figure on this bill is in kVA. kVA and kW are not "
                "interchangeable; please confirm the sanctioned load in kW."
            )
    if load is None:
        warnings.append(
            "Could not find the sanctioned load — please enter it from your bill. "
            "It caps the system size, so it is not something we will guess."
        )

    period_from, period_to, span = _find_period(text)
    months = None
    if span is not None:
        months = max(1, round(span / _MONTH_DAYS))
        if span not in _MONTHLY_SPAN:
            warnings.append(
                f"This bill appears to cover {span} days (about {months} months). "
                "Enter the units for ONE month — we do not convert a bimonthly "
                "bill automatically, because the bimonthly slab allowance is not a "
                "straight multiple of the monthly one."
            )
    elif units is not None:
        warnings.append(
            "Could not read the service period, so we cannot tell whether these "
            "units cover one month or two. Enter the units for ONE month."
        )

    tariff = None
    if m := _TARIFF.search(text):
        tariff = re.sub(r"\s+", "", m.group(1)).upper()

    phase = None
    if m := _PHASE.search(text):
        word, digit = m.group(1), m.group(2)
        if word:
            phase = word.upper()
        elif digit:
            phase = "SINGLE" if digit == "1" else "THREE"

    return BillFields(
        billed_units_kwh=units,
        billing_period_days=span,
        billing_period_months=months,
        period_from=period_from,
        period_to=period_to,
        sanctioned_load_kw=load,
        tariff_category=tariff,
        phase=phase,
        warnings=tuple(warnings),
    )
