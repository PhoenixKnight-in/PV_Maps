"""The allocator — PHASE 2 GROUNDWORK. Not part of the Phase 1 product.

    !! This module implements shared-quota allocation across a distribution
    !! transformer. PRD v1.1 lists "capacity allocation between neighbours" as
    !! an explicit Phase 1 NON-GOAL (PRD 3.2), and Phase 1 must never show a
    !! quota remaining, a queue position, a grid-approved capacity, or an
    !! approval prediction (PRD 2.3).
    !!
    !! An earlier PRD revision numbered this FR-5 and called it "the core
    !! invention". That is no longer true of the current document: FR-5 is now
    !! the interface requirement, and the utility-data work this module
    !! anticipates lives in FR-7, Grid Passport, which begins only after
    !! authorised TNPDCL data access exists (PRD 9). Nothing here is reachable
    !! until then.

Three strategies over the same instance:

    OPTIMAL       CP-SAT, value-maximising            <- what the grid could get
    FCFS          arrival order                       <- what the grid gets today
    LARGEST_ROOF  biggest roof first                  <- what an installer does

The delta between them is the argument for Grid Passport, not a Phase 1 output.

Pure. No DB, no I/O. Imported by nothing in `pvmaps.api` — see the note in
`api/main.py` — and it must stay that way while Phase 1 ships.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import ROUND_DOWN, Decimal

from pvmaps.phase2.allocator.models import (
    KWP_STEP,
    Allocation,
    Quota,
    Roof,
    Solution,
    Strategy,
)

__all__ = ["delta", "solve", "solve_all"]

_ZERO = Decimal(0)
_SCALE = Decimal(100)  # rupees -> paise, so CP-SAT sees integers only


def _steps(kwp: Decimal) -> int:
    """kWp -> whole 0.5 kW steps, rounded DOWN.

    Down, never nearest: rounding a 2.9 kW ceiling up to 3.0 would hand out
    capacity the roof or the sanctioned load does not have, and the resulting
    application dies at DISCOM feasibility -- the exact failure this product
    exists to predict.
    """
    return int((kwp / KWP_STEP).to_integral_value(rounding=ROUND_DOWN))


def _greedy(
    roofs: Sequence[Roof], quota: Quota, w: Decimal, order: Iterable[Roof], strategy: Strategy
) -> Solution:
    """Serve `order` until the quota runs out. Shared by FCFS and LARGEST_ROOF."""
    budget = _steps(quota.remaining_kw)
    allocations = []

    for roof in order:
        if budget <= 0:
            break
        take = min(_steps(roof.eligible_kwp), budget)
        if take <= 0:
            continue
        budget -= take
        allocations.append(
            Allocation(
                building_id=roof.building_id,
                kwp=take * KWP_STEP,
                value_private=roof.value_private,
                value_fiscal=roof.value_fiscal,
            )
        )

    return Solution(
        dt_id=quota.dt_id,
        strategy=strategy,
        weight_private=w,
        allocations=tuple(allocations),
        quota_remaining_kw=budget * KWP_STEP,
        is_proven_optimal=False,
    )


def _solve_optimal(roofs: Sequence[Roof], quota: Quota, w: Decimal) -> Solution:
    """Bounded knapsack via CP-SAT.

    Values are scaled to integer paise. CP-SAT is an integer solver; handing it
    floats would silently round the objective and quietly break the delta that
    the whole demo rests on.
    """
    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "OR-Tools is required for OPTIMAL. Install with: uv sync"
        ) from exc

    budget = _steps(quota.remaining_kw)
    model = cp_model.CpModel()

    caps = [_steps(r.eligible_kwp) for r in roofs]
    xs = [
        model.NewIntVar(0, cap, f"x[{r.building_id}]")
        for r, cap in zip(roofs, caps, strict=True)
    ]

    model.Add(sum(xs) <= budget)

    # value per STEP, in integer paise
    coeffs = [
        int((r.value_at(w) * KWP_STEP * _SCALE).to_integral_value(rounding=ROUND_DOWN))
        for r in roofs
    ]
    model.Maximize(sum(c * x for c, x in zip(coeffs, xs, strict=True)))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    solver.parameters.num_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(
            f"{quota.dt_id}: CP-SAT returned {solver.StatusName(status)}. "
            "The instance should always be feasible (x=0 is valid) -- this is a bug."
        )

    allocations = tuple(
        Allocation(
            building_id=r.building_id,
            kwp=solver.Value(x) * KWP_STEP,
            value_private=r.value_private,
            value_fiscal=r.value_fiscal,
        )
        for r, x in zip(roofs, xs, strict=True)
        if solver.Value(x) > 0
    )
    used = sum(solver.Value(x) for x in xs)

    return Solution(
        dt_id=quota.dt_id,
        strategy="OPTIMAL",
        weight_private=w,
        allocations=allocations,
        quota_remaining_kw=(budget - used) * KWP_STEP,
        is_proven_optimal=status == cp_model.OPTIMAL,
    )


def solve(
    roofs: Sequence[Roof],
    quota: Quota,
    strategy: Strategy,
    weight_private: Decimal = Decimal(1),
) -> Solution:
    """Allocate `quota` across `roofs` under `strategy`."""
    if not roofs:
        return Solution(
            dt_id=quota.dt_id,
            strategy=strategy,
            weight_private=weight_private,
            allocations=(),
            quota_remaining_kw=quota.remaining_kw,
            is_proven_optimal=True,
        )

    seen = {r.building_id for r in roofs}
    if len(seen) != len(roofs):
        raise ValueError(f"{quota.dt_id}: duplicate building_id in roof set")

    match strategy:
        case "OPTIMAL":
            return _solve_optimal(roofs, quota, weight_private)
        case "FCFS":
            order = sorted(roofs, key=lambda r: (r.fcfs_rank, r.building_id))
            return _greedy(roofs, quota, weight_private, order, "FCFS")
        case "LARGEST_ROOF":
            order = sorted(roofs, key=lambda r: (-r.roof_cap_kwp, r.building_id))
            return _greedy(roofs, quota, weight_private, order, "LARGEST_ROOF")
        case _:  # pragma: no cover
            raise ValueError(f"unknown strategy: {strategy!r}")


def solve_all(
    roofs: Sequence[Roof],
    quota: Quota,
    weight_private: Decimal = Decimal(1),
) -> dict[Strategy, Solution]:
    """All three strategies on one instance. FR-5.1."""
    return {
        s: solve(roofs, quota, s, weight_private)
        for s in ("OPTIMAL", "FCFS", "LARGEST_ROOF")
    }


def delta(solutions: dict[Strategy, Solution], w: Decimal | None = None) -> dict[str, Decimal]:
    """The number demo beat 4 is built on.

    PRD 11: "Same 14 kW: FCFS Rs 1.3 L/yr vs allocated-by-value Rs 4.1 L/yr.
    Same panels. Same sun. 3x. The difference is who gets them."
    """
    opt = solutions["OPTIMAL"].objective(w)
    fcfs = solutions["FCFS"].objective(w)
    lr = solutions["LARGEST_ROOF"].objective(w)
    return {
        "optimal": opt,
        "fcfs": fcfs,
        "largest_roof": lr,
        "gain_over_fcfs": opt - fcfs,
        "gain_over_largest_roof": opt - lr,
        "multiple_over_fcfs": (opt / fcfs) if fcfs > _ZERO else _ZERO,
    }
