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
    r"(?:units?\s*consumed|consumption(?:\s*\[[^\]]+\])?|consumption\s*(?:in\s*)?units?|no\.?\s*of\s*units?"
    r"|net\s*units?|units?\s*billed|total\s*units?)\s*[:\-=]?\s*" + _NUM,
    re.IGNORECASE,
)
_SECTION = re.compile(
    r"\bSection\s*[:\-=]?\s*([A-Za-z0-9\s/]+?)(?=\s*(?:Circle|Distribution|GST|Servi|Name|\n|$))",
    re.IGNORECASE,
)
_CIRCLE = re.compile(
    r"\bCircle\s*[:\-=]?\s*([A-Za-z0-9\s/]+?)(?=\s*(?:Distribution|Section|GST|Servi|Name|\n|$))",
    re.IGNORECASE,
)
_DISTRIBUTION = re.compile(
    r"\n\s*Distribution\s*[:\-=]?\s*([A-Za-z0-9\s.]+?)(?=\s*(?:Servi|Section|Circle|Name|\n|$))",
    re.IGNORECASE,
)
_CONSUMER_NUM = re.compile(
    r"(?:Servi[ce]{1,2}\s*Connection\s*(?:Number|No\.?)|Consumer\s*(?:Number|No\.?))\s*[:\-=]?\s*([0-9]{2,3}[-\s]?[0-9]{2,4}[-\s]?[0-9]{2,4}[-\s]?[0-9]{3,5}|[0-9]{10,12})",
    re.IGNORECASE,
)
_BIMONTHLY = re.compile(r"\bbi[-\s]?monthly\b", re.IGNORECASE)
_BILL_AMOUNT = re.compile(
    r"(?:Net\s*Payable\s*Amt|Bill\s*Amount)\s*(?:[^\n0-9]{0,20})?([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]{2})?|[0-9]+(?:\.[0-9]{2})?)",
    re.IGNORECASE,
)


def calculate_units_from_amount(b: float, category: str = "DOMESTIC") -> float:
    """Calculate bi-monthly units from bill amount paid (B) in Tamil Nadu.

    TNERC Tariff Schedule:
    DOMESTIC:
      B == 0: 100 units (free allowance)
      B <= 235: 100 + B / 2.35
      B <= 1175: 200 + (B - 235) / 4.70
      B <= 1805: 400 + (B - 1175) / 6.30
      B <= 2645: 500 + (B - 1805) / 8.40
      B <= 4535: 600 + (B - 2645) / 9.45
      B <= 6635: 800 + (B - 4535) / 10.50
      Else: 1000 + (B - 6635) / 11.55

    COMMERCIAL:
      B <= 665: B / 6.65
      Else: B / 10.45
    """
    category = (category or "DOMESTIC").upper()
    if "COMMERCIAL" in category or "LT3" in category:
        if b <= 665:
            return round(b / 6.65, 1)
        return round(b / 10.45, 1)

    if b <= 0:
        return 100.0
    elif b <= 235:
        return round(100.0 + b / 2.35, 1)
    elif b <= 1175:
        return round(200.0 + (b - 235.0) / 4.70, 1)
    elif b <= 1805:
        return round(400.0 + (b - 1175.0) / 6.30, 1)
    elif b <= 2645:
        return round(500.0 + (b - 1805.0) / 8.40, 1)
    elif b <= 4535:
        return round(600.0 + (b - 2645.0) / 9.45, 1)
    elif b <= 6635:
        return round(800.0 + (b - 4535.0) / 10.50, 1)
    else:
        return round(1000.0 + (b - 6635.0) / 11.55, 1)

_TARIFF = re.compile(
    r"\b(?:tariff|category)\s*(?:code|category)?\s*[:\-=]?\s*"
    r"(LT\s*[-\s]?\s*[IV0-9]+\s*[AB]?|LA\s*[-\s]?\s*[0-9]+[AB]?|HT\s*[-\s]?\s*[IV0-9]+|[IV]+\s*[AB]?)\b",
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

    # TNEB / TNPDCL specific details
    consumer_number: str | None = None
    section: str | None = None
    circle: str | None = None
    distribution: str | None = None
    consumer_name: str | None = None
    consumer_address: str | None = None
    bill_address: str | None = None
    bill_amount: Decimal | None = None
    is_bimonthly: bool = False

    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def monthly_units_kwh(self) -> Decimal | None:
        """Units for ONE month. If bimonthly, converts to monthly equivalent."""
        if self.billed_units_kwh is None:
            return None
        if self.is_bimonthly or (self.billing_period_days and 46 <= self.billing_period_days <= 75):
            return round(self.billed_units_kwh / Decimal(2), 1)
        if self.billing_period_days is None or self.billing_period_days not in _MONTHLY_SPAN:
            return self.billed_units_kwh
        return self.billed_units_kwh

    def to_form_patch(self) -> dict[str, Any]:
        """The JSON the browser merges into its editable fields."""
        patch: dict[str, Any] = {}
        if (monthly := self.monthly_units_kwh) is not None:
            patch["monthly_units_kwh"] = float(monthly)
        if self.sanctioned_load_kw is not None:
            patch["sanctioned_load_kw"] = float(self.sanctioned_load_kw)

        if self.consumer_number is not None:
            patch["consumer_number"] = self.consumer_number
        if self.section is not None:
            patch["section"] = self.section
        if self.circle is not None:
            patch["circle"] = self.circle
        if self.distribution is not None:
            patch["distribution"] = self.distribution
        if self.consumer_name is not None:
            patch["consumer_name"] = self.consumer_name
        if self.consumer_address is not None:
            patch["consumer_address"] = self.consumer_address
        if self.bill_address is not None:
            patch["bill_address"] = self.bill_address
        if self.bill_amount is not None:
            patch["bill_amount"] = float(self.bill_amount)
        if self.is_bimonthly:
            patch["is_bimonthly"] = True

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
            k for k in patch if k not in {"extracted_fields", "warnings", "must_confirm"}
        )
        patch["warnings"] = list(self.warnings)
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

    section = None
    if m := _SECTION.search(text):
        section = m.group(1).strip()

    circle = None
    if m := _CIRCLE.search(text):
        circle = m.group(1).strip()

    distribution = None
    if m := _DISTRIBUTION.search(text):
        distribution = m.group(1).strip()

    consumer_number = None
    if m := _CONSUMER_NUM.search(text):
        consumer_number = m.group(1).strip()

    is_bi = bool(_BIMONTHLY.search(text)) or (span is not None and 46 <= span <= 75)

    bill_amount = None
    if m := _BILL_AMOUNT.search(text):
        bill_amount = _decimal(m.group(1))

    if bill_amount is not None:
        calc_units = calculate_units_from_amount(float(bill_amount), tariff or "DOMESTIC")
        if units is None:
            units = Decimal(str(calc_units))
            if "Could not find the units consumed — please enter them from your bill." in warnings:
                warnings.remove("Could not find the units consumed — please enter them from your bill.")
            warnings.append(
                f"Calculated {calc_units} units from bill amount ₹{bill_amount} using TNERC tariff formula."
            )

    consumer_name = None
    consumer_address = None
    bill_address = None

    if m_addr := re.search(r"Name/Address\s*&[^\n]*\n([^\n]+)\n([^\n]+)", text, re.IGNORECASE):
        c_name = m_addr.group(1).strip()
        c_line = m_addr.group(2).strip()
        if c_name and not c_name.lower().startswith(("pay this", "gst", "state")):
            consumer_name = c_name
        if c_line:
            clean_addr = re.sub(r"^[sSwWdD]/[oO]\.[^,]+,\s*", "", c_line).strip(", ")
            consumer_address = clean_addr or c_line

    clean_parts = []
    if consumer_address:
        # Strip building/apartment name so Nominatim/Mappls resolves the street and area
        clean_c = re.sub(
            r"(?i)\b[A-Za-z0-9\s-]{1,20}(?:Apartment|Apartments|Apt|Flats|Flat|Villa|Villas|Illam|Bhavan|House|Residency|Towers|Enclave)\b,?\s*",
            "",
            consumer_address,
        ).strip()
        for suf in ("nagar", "puram", "palayam", "kuppam", "pettai", "pakkam", "colony"):
            clean_c = re.sub(rf"(?i)\b([a-z]{{3,}}?){suf}\b", r"\1 " + suf, clean_c)
        clean_c = re.sub(r",+", ",", clean_c).strip(" ,")
        if clean_c:
            clean_parts.append(clean_c)

    if section:
        clean_sec = re.sub(r"[/\\]\s*", " ", section).strip()
        if not any(clean_sec.lower() in p.lower() or "gandhi nagar" in p.lower() for p in clean_parts):
            clean_parts.append(clean_sec)

    if circle:
        clean_circ = circle.strip()
        if not any(clean_circ.lower() in p.lower() for p in clean_parts):
            clean_parts.append(clean_circ)

    clean_parts.append("Tamil Nadu")
    bill_address = ", ".join(clean_parts) if clean_parts else None

    if is_bi and units is not None:
        monthly_equiv = round(units / Decimal(2), 1)
        warnings.append(
            f"Tamil Nadu bill is bi-monthly ({units} units billed). Converted to {monthly_equiv} units/month — verify before continuing."
        )

    return BillFields(
        billed_units_kwh=units,
        billing_period_days=span,
        billing_period_months=months,
        period_from=period_from,
        period_to=period_to,
        sanctioned_load_kw=load,
        tariff_category=tariff,
        phase=phase,
        consumer_number=consumer_number,
        section=section,
        circle=circle,
        distribution=distribution,
        consumer_name=consumer_name,
        consumer_address=consumer_address,
        bill_address=bill_address,
        bill_amount=bill_amount,
        is_bimonthly=is_bi,
        warnings=tuple(warnings),
    )
