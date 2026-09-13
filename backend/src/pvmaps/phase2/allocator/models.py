"""Value objects for the allocator. Pure data — no DB, no I/O.

PHASE 2 GROUNDWORK. See `solve.py` for why this is not a Phase 1 capability:
shared-quota allocation is a PRD 3.2 non-goal in Phase 1, and the objective
below describes work that belongs to FR-7 (Grid Passport), after authorised
TNPDCL data access exists.

    maximise  sum(v_i * kWp_i)
    s.t.      sum(kWp_i) <= Q_remaining(DT)          <- shared quota
              kWp_i      <= min(roof_cap_i, sanctioned_load_i)
    where     v_i = w * private_Rs_i + (1-w) * subsidy_avoided_i
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

__all__ = ["KWP_STEP", "Allocation", "Quota", "Roof", "Solution", "Strategy"]

Strategy = Literal["OPTIMAL", "FCFS", "LARGEST_ROOF"]

KWP_STEP = Decimal("0.5")
"""Plant sizes are quantised to 0.5 kW.

Panels come in discrete wattages and inverters in discrete sizes, so a
continuous LP relaxation would return capacities nobody can install. Quantising
also turns FR-5 into a pure integer program, which is what lets CP-SAT prove
optimality in milliseconds instead of approximating it.
"""


@dataclass(frozen=True, slots=True)
class Roof:
    """One candidate on a transformer."""

    building_id: str

    roof_cap_kwp: Decimal
    """Physics ceiling from usable_area (FR-1.3, FR-2). Constraint #1."""

    sanctioned_load_kw: Decimal
    """The consumer's contract with TNPDCL. Constraint #2 -- PRD 2.1, and
    the one almost nobody models. On demo beat 1 this is what strikes through
    the confident roof number."""

    value_private: Decimal
    """Rs/year per installed kWp, to the household. From the MARGINAL slab
    rate (FR-4.1), never the average tariff. This is Rs 0 for a household in
    the free slab, and that zero is honest."""

    value_fiscal: Decimal
    """Rs/year per installed kWp of subsidy the state stops paying (FR-4.4)."""

    fcfs_rank: int
    """Arrival order in the queue. The status quo allocates on this alone --
    "whoever an installer door-knocked first" (PRD 2.3)."""

    def __post_init__(self) -> None:
        for name in ("roof_cap_kwp", "sanctioned_load_kw", "value_private", "value_fiscal"):
            if getattr(self, name) < 0:
                raise ValueError(f"{self.building_id}: {name} cannot be negative")

    @property
    def eligible_kwp(self) -> Decimal:
        """Ceiling before the shared quota is considered.

        Note this is only two of the PRD's three constraints. The third -- the
        DT quota -- is not a property of a roof at all. It is shared, and that
        is the entire point of the product.
        """
        return min(self.roof_cap_kwp, self.sanctioned_load_kw)

    def value_at(self, w: Decimal) -> Decimal:
        """v_i = w * private + (1-w) * fiscal.

        w=1 is the consumer-facing view (demo beat 2); w=0 is the policy-facing
        view. PRD 12.3 leaves the default open -- it lives in
        config/regulations/tnerc.json, not here.
        """
        if not (0 <= w <= 1):
            raise ValueError(f"weight must be in [0, 1], got {w}")
        return w * self.value_private + (Decimal(1) - w) * self.value_fiscal


@dataclass(frozen=True, slots=True)
class Quota:
    """The scarce, shared, expiring thing (PRD G3)."""

    dt_id: str
    remaining_kw: Decimal

    def __post_init__(self) -> None:
        if self.remaining_kw < 0:
            raise ValueError(f"{self.dt_id}: remaining quota cannot be negative")


@dataclass(frozen=True, slots=True)
class Allocation:
    building_id: str
    kwp: Decimal
    value_private: Decimal
    value_fiscal: Decimal


@dataclass(frozen=True, slots=True)
class Solution:
    dt_id: str
    strategy: Strategy
    weight_private: Decimal
    allocations: tuple[Allocation, ...]
    quota_remaining_kw: Decimal
    is_proven_optimal: bool
    """True only for OPTIMAL, and only when CP-SAT proved it (not just found it)."""

    @property
    def total_kwp(self) -> Decimal:
        return sum((a.kwp for a in self.allocations), start=Decimal(0))

    @property
    def total_private(self) -> Decimal:
        """Rs/year to households under this strategy."""
        return sum((a.kwp * a.value_private for a in self.allocations), start=Decimal(0))

    @property
    def total_fiscal(self) -> Decimal:
        """Rs/year of subsidy avoided under this strategy."""
        return sum((a.kwp * a.value_fiscal for a in self.allocations), start=Decimal(0))

    def objective(self, w: Decimal | None = None) -> Decimal:
        w = self.weight_private if w is None else w
        return w * self.total_private + (Decimal(1) - w) * self.total_fiscal

    @property
    def households_served(self) -> int:
        return sum(1 for a in self.allocations if a.kwp > 0)
