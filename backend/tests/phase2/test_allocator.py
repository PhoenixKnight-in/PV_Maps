"""Allocator tests — PRD 8.1, with one correction.

The PRD states the criterion as:

    "optimal >= largest_roof >= FCFS on randomised instances;
     quota constraint never violated"

Only part of that is a theorem, and encoding the rest as a pointwise assertion
would produce a test that fails randomly the week of the demo:

  INVARIANT   optimal >= FCFS, optimal >= largest_roof
              True always, by definition of the maximum. Hypothesis.

  INVARIANT   sum(kWp) <= Q_remaining, for all three strategies.
              True always. Hypothesis.

  TENDENCY    largest_roof >= FCFS
              NOT an invariant. FCFS can get lucky -- a high-consumption
              household may simply have arrived first. Holds in expectation,
              and only because roof size correlates with consumption. Tested as
              a seeded Monte-Carlo comparison of means.

See ARCHITECTURE.md 12.
"""

from __future__ import annotations

import random
from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pvmaps.phase2.allocator import KWP_STEP, Quota, Roof, delta, solve, solve_all

pytest.importorskip("ortools", reason="OR-Tools required for OPTIMAL")

STRATEGIES = ("OPTIMAL", "FCFS", "LARGEST_ROOF")


@st.composite
def instance(draw: st.DrawFn) -> tuple[list[Roof], Quota]:
    """A transformer with 1-12 competing roofs.

    PRD 11 beat 3 describes a real one: '100 kVA, 76 kW taken, 14 kW left,
    23 competing roofs.'
    """
    n = draw(st.integers(min_value=1, max_value=12))
    ranks = draw(st.permutations(range(n)))

    roofs = [
        Roof(
            building_id=f"b{i}",
            roof_cap_kwp=Decimal(draw(st.integers(0, 20))) * KWP_STEP,
            sanctioned_load_kw=Decimal(draw(st.integers(0, 20))) * KWP_STEP,
            value_private=Decimal(draw(st.integers(0, 20_000))),
            value_fiscal=Decimal(draw(st.integers(0, 20_000))),
            fcfs_rank=ranks[i],
        )
        for i in range(n)
    ]
    quota = Quota(dt_id="dt-test", remaining_kw=Decimal(draw(st.integers(0, 60))) * KWP_STEP)
    return roofs, quota


_SETTINGS = settings(
    max_examples=150,
    deadline=None,  # CP-SAT startup is lumpy
    suppress_health_check=[HealthCheck.too_slow],
)


@given(instance())
@_SETTINGS
def test_quota_is_never_violated(inst: tuple[list[Roof], Quota]) -> None:
    """The hard constraint. A violation here is a system that tells a household
    their application will be approved when the DISCOM will reject it."""
    roofs, quota = inst
    for strategy in STRATEGIES:
        sol = solve(roofs, quota, strategy)
        assert sol.total_kwp <= quota.remaining_kw, f"{strategy} overran the quota"
        assert sol.quota_remaining_kw >= 0


@given(instance())
@_SETTINGS
def test_optimal_dominates_both_baselines(inst: tuple[list[Roof], Quota]) -> None:
    """The only ordering that is a theorem."""
    roofs, quota = inst
    sols = solve_all(roofs, quota)
    opt = sols["OPTIMAL"].objective()

    assert opt >= sols["FCFS"].objective()
    assert opt >= sols["LARGEST_ROOF"].objective()


@given(instance())
@_SETTINGS
def test_no_roof_exceeds_its_own_ceiling(inst: tuple[list[Roof], Quota]) -> None:
    """PRD 1.1 constraints #1 and #2: roof geometry and sanctioned load."""
    roofs, quota = inst
    by_id = {r.building_id: r for r in roofs}
    for strategy in STRATEGIES:
        for a in solve(roofs, quota, strategy).allocations:
            assert a.kwp <= by_id[a.building_id].eligible_kwp


@given(instance())
@_SETTINGS
def test_allocations_are_installable_sizes(inst: tuple[list[Roof], Quota]) -> None:
    """Every allocation is a whole multiple of KWP_STEP -- nobody can install
    3.27 kW."""
    roofs, quota = inst
    for strategy in STRATEGIES:
        for a in solve(roofs, quota, strategy).allocations:
            assert (a.kwp / KWP_STEP) % 1 == 0


@given(instance())
@_SETTINGS
def test_optimal_is_proven_not_merely_found(inst: tuple[list[Roof], Quota]) -> None:
    """At pilot scale (tens of roofs) CP-SAT should always prove optimality
    inside the time limit. If this starts failing, the instance has grown
    beyond what the demo claims."""
    roofs, quota = inst
    assert solve(roofs, quota, "OPTIMAL").is_proven_optimal


# --------------------------------------------------------------------------
# The tendency, tested honestly
# --------------------------------------------------------------------------


def _correlated_instance(rng: random.Random, n: int = 23) -> tuple[list[Roof], Quota]:
    """A transformer where roof size correlates with consumption.

    This correlation is the ONLY reason LARGEST_ROOF beats FCFS: a bigger roof
    usually means a bigger house, higher consumption, a higher marginal slab
    and therefore more value per kWp. It is a real effect, but it is an
    assumption about the pilot ward -- not a property of the algorithm.
    """
    roofs = []
    for i in range(n):
        cap_steps = rng.randint(2, 20)
        cap = Decimal(cap_steps) * KWP_STEP
        # value rises with roof size, with real noise on top
        base = Decimal(cap_steps * 900)
        noise = Decimal(rng.randint(-3000, 3000))
        roofs.append(
            Roof(
                building_id=f"b{i}",
                roof_cap_kwp=cap,
                sanctioned_load_kw=Decimal(rng.randint(2, 20)) * KWP_STEP,
                value_private=max(Decimal(0), base + noise),
                value_fiscal=Decimal(rng.randint(0, 5_000)),
                fcfs_rank=i,
            )
        )
    # Arrival order is independent of value -- that is the whole point of FCFS.
    rng.shuffle(roofs)
    roofs = [replace(r, fcfs_rank=i) for i, r in enumerate(roofs)]

    # PRD 11 beat 3: 14 kW left on a 100 kVA transformer.
    return roofs, Quota(dt_id="dt-demo", remaining_kw=Decimal(14))


def test_largest_roof_beats_fcfs_on_average_not_pointwise() -> None:
    """The PRD's ordering claim, tested as what it actually is.

    Also records how often FCFS wins outright. That number is not a defect --
    it is the strongest available answer to "isn't first-come-first-served
    basically fine?" It is fine sometimes. That is exactly why nobody notices
    it is failing.
    """
    rng = random.Random(20260910)
    runs = 200
    opt_total = fcfs_total = lr_total = Decimal(0)
    fcfs_beats_lr = 0

    for _ in range(runs):
        roofs, quota = _correlated_instance(rng)
        sols = solve_all(roofs, quota)
        opt_v, fcfs_v, lr_v = (sols[s].objective() for s in STRATEGIES)

        assert opt_v >= fcfs_v and opt_v >= lr_v   # invariant, every single time
        opt_total += opt_v
        fcfs_total += fcfs_v
        lr_total += lr_v
        if fcfs_v > lr_v:
            fcfs_beats_lr += 1

    assert lr_total > fcfs_total, "largest-roof should win on average"
    assert opt_total > lr_total

    # FCFS genuinely wins some instances. Pointwise assertion would flake.
    assert fcfs_beats_lr > 0, (
        "FCFS never won in 200 runs -- the generator's correlation is probably "
        "too strong to be a fair test of the claim"
    )


def test_delta_is_the_product() -> None:
    """PRD FR-5.2 / demo beat 4: 'Same panels. Same sun. The difference is who
    gets them.'"""
    rng = random.Random(7)
    roofs, quota = _correlated_instance(rng)
    d = delta(solve_all(roofs, quota))

    assert d["gain_over_fcfs"] >= 0
    assert d["optimal"] >= d["fcfs"]
    assert d["multiple_over_fcfs"] >= 1


# --------------------------------------------------------------------------
# Edges
# --------------------------------------------------------------------------


def test_exhausted_quota_allocates_nothing() -> None:
    """A full transformer. PRD 1.3: 'Once a DT fills, the allocation is
    irreversible.'"""
    roofs = [Roof("b0", Decimal(10), Decimal(10), Decimal(5000), Decimal(0), 0)]
    for strategy in STRATEGIES:
        sol = solve(roofs, Quota("dt", Decimal(0)), strategy)
        assert sol.total_kwp == 0
        assert sol.allocations == ()


def test_sanctioned_load_binds_before_the_roof() -> None:
    """PRD 1.1: 'Indian urban roofs are flat and generous. Sanctioned loads are
    small.' Demo beat 1 is this line."""
    roof = Roof("b0", roof_cap_kwp=Decimal("6.5"), sanctioned_load_kw=Decimal(3),
                value_private=Decimal(5000), value_fiscal=Decimal(0), fcfs_rank=0)
    assert roof.eligible_kwp == Decimal(3)

    sol = solve([roof], Quota("dt", Decimal(50)), "OPTIMAL")
    assert sol.total_kwp == Decimal(3)


def test_zero_value_roof_is_not_allocated_scarce_quota() -> None:
    """The free-slab household (PRD 1.2). Worth Rs 0, so under OPTIMAL the
    quota goes to the neighbour -- while FCFS hands it over on arrival order.

    PRD 10: the verb is *route*, never *reject*.
    """
    free_slab = Roof("free", Decimal(10), Decimal(10), Decimal(0), Decimal(0), fcfs_rank=0)
    neighbour = Roof("nbr", Decimal(10), Decimal(10), Decimal(11_550), Decimal(0), fcfs_rank=1)
    quota = Quota("dt", Decimal(3))

    opt = solve([free_slab, neighbour], quota, "OPTIMAL")
    assert {a.building_id for a in opt.allocations} == {"nbr"}

    fcfs = solve([free_slab, neighbour], quota, "FCFS")
    assert {a.building_id for a in fcfs.allocations} == {"free"}
    assert fcfs.objective() == 0


def test_duplicate_building_ids_are_rejected() -> None:
    roofs = [
        Roof("dup", Decimal(5), Decimal(5), Decimal(100), Decimal(0), 0),
        Roof("dup", Decimal(5), Decimal(5), Decimal(200), Decimal(0), 1),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        solve(roofs, Quota("dt", Decimal(10)), "OPTIMAL")


def test_weight_shifts_the_objective_between_private_and_fiscal() -> None:
    """FR-5: v_i = w * private + (1-w) * subsidy_avoided. PRD 12.3 leaves the
    default open; both views must actually work."""
    private_heavy = Roof("p", Decimal(5), Decimal(5), Decimal(10_000), Decimal(0), 0)
    fiscal_heavy = Roof("f", Decimal(5), Decimal(5), Decimal(0), Decimal(10_000), 1)
    quota = Quota("dt", Decimal(5))

    consumer_view = solve([private_heavy, fiscal_heavy], quota, "OPTIMAL", Decimal(1))
    policy_view = solve([private_heavy, fiscal_heavy], quota, "OPTIMAL", Decimal(0))

    assert {a.building_id for a in consumer_view.allocations} == {"p"}
    assert {a.building_id for a in policy_view.allocations} == {"f"}
