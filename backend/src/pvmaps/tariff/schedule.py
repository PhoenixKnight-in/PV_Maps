"""Versioned tariff schedules, loaded from config/tariffs/*.json.

PRD NFR-4: "Tariff schedules and regulation parameters live in versioned config,
never hardcoded." PRD FR-4.5: schedules are versioned with `effective_from`.

Everything here is Decimal. PRD 10 (acceptance criteria) requires the computed bill to match five real
TNPDCL bills TO THE RUPEE; binary floats will cost a paisa on a telescopic sum
and there is no way to argue that away on stage.
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

__all__ = [
    "CONFIG_DIR",
    "Slab",
    "TariffSchedule",
    "available_versions",
    "load_schedule",
    "slab_label",
]

_PKG_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = Path(os.environ.get("PVMAPS_TARIFF_DIR", _PKG_ROOT / "config" / "tariffs"))


def slab_label(slab_from: int, slab_to: int | None) -> str:
    """Render slab bounds the way a paper bill prints them: "101-200", "401+".

    Shared by `Slab` and `tariff.engine.Block` so that a label on screen can be
    checked against a bill in someone's hand without a mental conversion.
    """
    upper = "+" if slab_to is None else f"-{slab_to}"
    return f"{slab_from + 1}{upper}"


@dataclass(frozen=True, slots=True)
class Slab:
    """One tariff block.

    Bounds are half-open on the left: `slab_from` is EXCLUSIVE, `slab_to` is
    INCLUSIVE. So Slab(100, 200, ...) covers units 101..200, which is how the
    PRD writes it ("101-200 Rs 4.70"). `slab_to=None` means unbounded.
    """

    slab_from: int
    slab_to: int | None
    rate: Decimal

    @property
    def label(self) -> str:
        return slab_label(self.slab_from, self.slab_to)

    def units_in(self, total_units: Decimal) -> Decimal:
        """How many of `total_units` land inside this slab."""
        upper = total_units if self.slab_to is None else min(total_units, Decimal(self.slab_to))
        return max(Decimal(0), upper - Decimal(self.slab_from))


@dataclass(frozen=True, slots=True)
class TariffSchedule:
    version: str
    effective_from: date
    category: str
    currency: str
    billing_period_months: int
    slabs: tuple[Slab, ...]
    source: str
    verification_status: str

    def __post_init__(self) -> None:
        if not self.slabs:
            raise ValueError(f"{self.version}: schedule has no slabs")
        if self.slabs[0].slab_from != 0:
            raise ValueError(f"{self.version}: first slab must start at 0")
        if self.slabs[-1].slab_to is not None:
            raise ValueError(
                f"{self.version}: last slab must be unbounded (slab_to=null), "
                "otherwise high consumers fall off the end of the schedule"
            )
        for prev, nxt in zip(self.slabs, self.slabs[1:], strict=False):
            if prev.slab_to is None:
                raise ValueError(f"{self.version}: unbounded slab is not last")
            if prev.slab_to != nxt.slab_from:
                raise ValueError(
                    f"{self.version}: slabs are not contiguous -- "
                    f"{prev.slab_to} then {nxt.slab_from}. A gap here silently "
                    "under-bills every consumer above it."
                )

    @property
    def is_verified(self) -> bool:
        return self.verification_status == "VERIFIED_AGAINST_PRIMARY_SOURCE"

    def slab_for(self, units: Decimal) -> Slab:
        """The slab the `units`-th unit falls into.

        That is the LAST unit consumed, which is the first one solar displaces
        -- so this is the marginal slab in the sense the product needs. Note
        the boundary: at exactly 100 units the 100th unit is still free, so
        slab_for(100) is the free slab, not the Rs 4.70 one.
        """
        for slab in self.slabs:
            if slab.slab_to is None or units <= Decimal(slab.slab_to):
                return slab
        return self.slabs[-1]  # unreachable given __post_init__

    def to_billing_period(self, months: int) -> TariffSchedule:
        """Rescale slab bounds to a different billing period.

        PRD 10 (must verify) OPEN QUESTION -- DO NOT TRUST THIS FOR TAMIL NADU BIMONTHLY.

        TN bills bimonthly, and the free allowance is reported to rise from 100
        to 200 units for consumers at or below 500 units bimonthly. That is a
        *conditional* allowance, not a linear scaling, so this method is wrong
        for the exact case the product cares about. It is here for schedules
        that genuinely do scale linearly. Read the primary TNERC order, then
        add the real bimonthly schedule as its own versioned JSON file.
        """
        raise NotImplementedError(
            "PRD 10 (must verify): bimonthly slab boundaries are unverified and are NOT a "
            "linear scaling of the monthly-equivalent schedule. Add a separate "
            "versioned schedule file once the primary TNERC order is read."
        )


def _parse(raw: dict[str, Any], *, version_hint: str) -> TariffSchedule:
    slabs = tuple(
        Slab(
            slab_from=int(s["slab_from"]),
            slab_to=None if s["slab_to"] is None else int(s["slab_to"]),
            # str() first: if someone puts a JSON number here, Decimal(float)
            # would inherit binary error. Fail loudly instead.
            rate=Decimal(str(s["rate"])),
        )
        for s in raw["slabs"]
    )
    return TariffSchedule(
        version=str(raw.get("version", version_hint)),
        effective_from=date.fromisoformat(str(raw["effective_from"])),
        category=str(raw["category"]),
        currency=str(raw.get("currency", "INR")),
        billing_period_months=int(raw.get("billing_period_months", 1)),
        slabs=slabs,
        source=str(raw.get("source", "")),
        verification_status=str(
            raw.get("verification_status", "UNVERIFIED_AGAINST_PRIMARY_SOURCE")
        ),
    )


@lru_cache(maxsize=32)
def load_schedule(version: str) -> TariffSchedule:
    """Load a schedule by version string or by filename stem."""
    for stem in (version, version.replace("-", "_")):
        path = CONFIG_DIR / f"{stem}.json"
        if path.exists():
            parsed: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            return _parse(parsed, version_hint=stem)

    for path in sorted(CONFIG_DIR.glob("*.json")):
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("version") == version:
            return _parse(raw, version_hint=path.stem)

    raise FileNotFoundError(
        f"no tariff schedule {version!r} in {CONFIG_DIR}. "
        f"available: {', '.join(available_versions()) or '(none)'}"
    )


def available_versions() -> list[str]:
    out = []
    for path in sorted(CONFIG_DIR.glob("*.json")):
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        out.append(str(raw.get("version", path.stem)))
    return out


def latest_for(category: str, on: date | None = None) -> TariffSchedule:
    """The schedule in force for `category` on `on` (default: today)."""
    on = on or date.today()
    candidates = [
        s
        for v in available_versions()
        if (s := load_schedule(v)).category == category and s.effective_from <= on
    ]
    if not candidates:
        raise LookupError(f"no {category} schedule effective on or before {on}")
    return max(candidates, key=lambda s: s.effective_from)
