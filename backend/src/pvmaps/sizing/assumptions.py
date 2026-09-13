"""Ranges, and the versioned assumption packs that supply them.

ARCHITECTURE.md 7:

    "The API must return ranges whenever the bill lacks interval-meter data.
     It must never represent a self-consumption estimate as an observed fact."

So `Range` is the working type of the whole sizing module. A point value only
appears where something is genuinely known -- a confirmed bill figure, a roof
polygon, a published tariff rate.

Loading is the only I/O in `pvmaps.sizing`. Everything downstream is pure.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from pvmaps.estimate import Estimate, Source

__all__ = [
    "Range",
    "SolarAssumptions",
    "SubsidySchedule",
    "SubsidyTier",
    "load_assumptions",
    "load_subsidy",
]

_PKG_ROOT = Path(__file__).resolve().parents[1]
_ASSUMPTIONS_DIR = Path(
    os.environ.get("PVMAPS_ASSUMPTIONS_DIR", _PKG_ROOT / "config" / "solar_assumptions")
)
_SUBSIDY_DIR = Path(os.environ.get("PVMAPS_SUBSIDY_DIR", _PKG_ROOT / "config" / "subsidies"))

_ZERO = Decimal(0)


def _d(x: Any) -> Decimal:
    """Decimal via str, always. A JSON float that reaches Decimal() directly
    carries its binary error into a rupee figure."""
    return x if isinstance(x, Decimal) else Decimal(str(x))


@dataclass(frozen=True, slots=True)
class Range:
    """A closed interval. `lo == hi` is a claim of certainty -- mean it."""

    lo: Decimal
    hi: Decimal

    def __post_init__(self) -> None:
        if self.lo > self.hi:
            raise ValueError(f"inverted range: lo={self.lo} > hi={self.hi}")

    @classmethod
    def of(cls, lo: Any, hi: Any) -> Range:
        return cls(_d(lo), _d(hi))

    @classmethod
    def exact(cls, v: Any) -> Range:
        d = _d(v)
        return cls(d, d)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Range:
        return cls(_d(raw["lo"]), _d(raw["hi"]))

    @property
    def is_certain(self) -> bool:
        return self.lo == self.hi

    @property
    def mid(self) -> Decimal:
        return (self.lo + self.hi) / 2

    @property
    def width(self) -> Decimal:
        return self.hi - self.lo

    # Interval arithmetic. Monotonic operations only -- every operand in this
    # module is non-negative, and the one place that is not (NPV, which can go
    # negative) is handled explicitly rather than by a general rule.
    def __add__(self, o: Range | Decimal | int) -> Range:
        o = o if isinstance(o, Range) else Range.exact(o)
        return Range(self.lo + o.lo, self.hi + o.hi)

    def __sub__(self, o: Range | Decimal | int) -> Range:
        """Note the crossed bounds: the worst case of a difference pairs our
        low with their high."""
        o = o if isinstance(o, Range) else Range.exact(o)
        return Range(self.lo - o.hi, self.hi - o.lo)

    def __mul__(self, o: Range | Decimal | int) -> Range:
        o = o if isinstance(o, Range) else Range.exact(o)
        products = (self.lo * o.lo, self.lo * o.hi, self.hi * o.lo, self.hi * o.hi)
        return Range(min(products), max(products))

    def __truediv__(self, o: Range | Decimal | int) -> Range:
        o = o if isinstance(o, Range) else Range.exact(o)
        if o.lo <= _ZERO <= o.hi:
            raise ZeroDivisionError(f"divisor range {o} spans zero")
        quotients = (self.lo / o.lo, self.lo / o.hi, self.hi / o.lo, self.hi / o.hi)
        return Range(min(quotients), max(quotients))

    def clamp(self, lo: Decimal, hi: Decimal) -> Range:
        return Range(min(max(self.lo, lo), hi), min(max(self.hi, lo), hi))

    def cap_at(self, ceiling: Range | Decimal) -> Range:
        """Elementwise min -- e.g. self-consumption cannot exceed generation."""
        c = ceiling if isinstance(ceiling, Range) else Range.exact(ceiling)
        return Range(min(self.lo, c.lo), min(self.hi, c.hi))

    def to_estimate(self, *, source: Source, confidence: float) -> Estimate[float]:
        """Cross into the API layer. Uses the midpoint as the headline value --
        never the optimistic bound."""
        return Estimate[float](
            value=float(self.mid),
            lo=float(self.lo),
            hi=float(self.hi),
            source=source,
            confidence=confidence,
        )

    def __str__(self) -> str:
        return f"{self.lo}" if self.is_certain else f"{self.lo}-{self.hi}"


@dataclass(frozen=True, slots=True)
class SolarAssumptions:
    version: str
    effective_from: date
    region: str
    verification_status: str

    specific_yield: Range
    """kWh per kWp per year."""

    area_per_kwp_m2: Range
    """Shadow-free roof area one kWp occupies, including array packing losses."""

    servable_archetypes: dict[str, Range]
    servable_modifiers: dict[str, Range]
    servable_floor: Decimal
    servable_ceiling: Decimal

    export_rate: Range
    installed_cost_per_kwp: Range
    annual_degradation_pct: Range
    system_lifetime_years: int
    discount_rate_pct: Range
    annual_om_per_kwp: Range

    @property
    def is_verified(self) -> bool:
        return self.verification_status == "VERIFIED_AGAINST_PRIMARY_SOURCE"

    @property
    def values_export(self) -> bool:
        """False while the export band is pinned at zero -- the UI must say
        'exported units are not counted' rather than silently ignoring them."""
        return self.export_rate.hi > _ZERO


@dataclass(frozen=True, slots=True)
class SubsidyTier:
    """Marginal, like a tariff slab: kwp_from EXCLUSIVE, kwp_to INCLUSIVE."""

    kwp_from: Decimal
    kwp_to: Decimal | None
    inr_per_kwp: Decimal

    def kwp_in(self, total: Decimal) -> Decimal:
        upper = total if self.kwp_to is None else min(total, self.kwp_to)
        return max(_ZERO, upper - self.kwp_from)


@dataclass(frozen=True, slots=True)
class SubsidySchedule:
    version: str
    effective_from: date
    verification_status: str
    central_tiers: tuple[SubsidyTier, ...]
    central_cap: Decimal
    state_tiers: tuple[SubsidyTier, ...]
    state_cap: Decimal
    max_kwp: Decimal

    @property
    def is_verified(self) -> bool:
        return self.verification_status == "VERIFIED_AGAINST_PRIMARY_SOURCE"

    def amount_for(self, kwp: Decimal) -> Decimal:
        """Total subsidy for a system of `kwp`. Monotonic non-decreasing in
        kwp, and capped."""
        if kwp < _ZERO:
            raise ValueError(f"system size cannot be negative: {kwp}")
        eligible = min(kwp, self.max_kwp)
        central = min(
            sum((t.kwp_in(eligible) * t.inr_per_kwp for t in self.central_tiers), start=_ZERO),
            self.central_cap,
        )
        state = min(
            sum((t.kwp_in(eligible) * t.inr_per_kwp for t in self.state_tiers), start=_ZERO),
            self.state_cap,
        )
        return central + state


def _tiers(raw: list[dict[str, Any]]) -> tuple[SubsidyTier, ...]:
    return tuple(
        SubsidyTier(
            kwp_from=_d(t["kwp_from"]),
            kwp_to=None if t["kwp_to"] is None else _d(t["kwp_to"]),
            inr_per_kwp=_d(t["inr_per_kwp"]),
        )
        for t in raw
    )


@lru_cache(maxsize=8)
def load_assumptions(version: str = "tn-inland-2025") -> SolarAssumptions:
    raw = _read(_ASSUMPTIONS_DIR, version)
    sf = raw["solar_servable_fraction"]
    return SolarAssumptions(
        version=str(raw["version"]),
        effective_from=date.fromisoformat(str(raw["effective_from"])),
        region=str(raw.get("region", "")),
        verification_status=str(
            raw.get("verification_status", "UNVERIFIED_AGAINST_PRIMARY_SOURCE")
        ),
        specific_yield=Range.from_json(raw["specific_yield_kwh_per_kwp_yr"]),
        area_per_kwp_m2=Range.from_json(raw["area_per_kwp_m2"]),
        servable_archetypes={k: Range.from_json(v) for k, v in sf["archetypes"].items()},
        servable_modifiers={k: Range.from_json(v) for k, v in sf["modifiers"].items()},
        servable_floor=_d(sf["floor"]),
        servable_ceiling=_d(sf["ceiling"]),
        export_rate=Range.from_json(raw["export_rate_inr_per_kwh"]),
        installed_cost_per_kwp=Range.from_json(raw["installed_cost_inr_per_kwp"]),
        annual_degradation_pct=Range.from_json(raw["annual_degradation_pct"]),
        system_lifetime_years=int(raw["system_lifetime_years"]),
        discount_rate_pct=Range.from_json(raw["discount_rate_pct"]),
        annual_om_per_kwp=Range.from_json(raw["annual_om_cost_inr_per_kwp"]),
    )


@lru_cache(maxsize=8)
def load_subsidy(version: str = "pm-surya-ghar-2024") -> SubsidySchedule:
    raw = _read(_SUBSIDY_DIR, version)
    return SubsidySchedule(
        version=str(raw["version"]),
        effective_from=date.fromisoformat(str(raw["effective_from"])),
        verification_status=str(
            raw.get("verification_status", "UNVERIFIED_AGAINST_PRIMARY_SOURCE")
        ),
        central_tiers=_tiers(raw["central"]["tiers"]),
        central_cap=_d(raw["central"]["cap_inr"]),
        state_tiers=_tiers(raw["state_top_up"]["tiers"]),
        state_cap=_d(raw["state_top_up"]["cap_inr"]),
        max_kwp=_d(raw["eligibility"]["max_kwp"]),
    )


def _read(directory: Path, version: str) -> dict[str, Any]:
    for stem in (version, version.replace("-", "_")):
        path = directory / f"{stem}.json"
        if path.exists():
            exact: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            return exact
    for path in sorted(directory.glob("*.json")):
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("version") == version:
            return raw
    available = [p.stem for p in sorted(directory.glob("*.json"))]
    raise FileNotFoundError(f"no {version!r} in {directory}. available: {available}")
