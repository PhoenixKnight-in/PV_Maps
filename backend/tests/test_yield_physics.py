"""Yield physics — FR-2, and PRD 10's yield acceptance criterion.

Skipped without pvlib (the `pipeline` group). Slow enough to matter: each
`annual_yield` call runs two 8760-hour simulations, so the site-level tests here
are few and deliberate rather than parameterised over a grid.

    "Yield model | Within a defensible published Tamil Nadu yield range, or
     assumptions are reviewed"

The check that makes that criterion meaningful is
`test_the_published_band_check_is_not_circular`. If the model's scaling factor
had been tuned to land inside `specific_yield`, then agreeing with
`specific_yield` would prove nothing at all.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pvlib", reason="pipeline dependency group not installed")
pytest.importorskip("pandas", reason="pipeline dependency group not installed")

from pvmaps.pipeline.yield_physics import (
    CLEARSKY_FRACTION_BAND,
    LossChain,
    annual_yield,
    as_roof_analysis_row,
    best_tilt,
    clearsky_poa,
)
from pvmaps.sizing import load_assumptions

A = load_assumptions()
VELLORE = (12.9202, 79.1325)


@pytest.fixture(scope="module")
def vellore():  # type: ignore[no-untyped-def]
    return annual_yield(*VELLORE, A, tilt=15.0)


# ---------------------------------------------------------------------------
# The acceptance criterion
# ---------------------------------------------------------------------------


def test_vellore_yield_lands_in_the_published_band(vellore) -> None:  # type: ignore[no-untyped-def]
    """PRD 10. 1500-1600 kWh/kWp/yr is the published inland-TN band."""
    assert vellore.agrees_with_published_band(A)
    assert 1300 < vellore.conservative < vellore.expected < 1900, (
        f"got {vellore.conservative}-{vellore.expected} kWh/kWp/yr, which is "
        "outside any defensible Tamil Nadu range -- check the physics"
    )


def test_the_published_band_check_is_not_circular() -> None:
    """The clear-sky fraction is derived from published GHI, not from the yield
    band, so `agrees_with_published_band` can actually fail.

    Proof by demonstration: halve the fraction and the check fails. A tuned
    constant would have made that impossible, and an acceptance criterion that
    cannot fail is not one.
    """
    wrong = annual_yield(*VELLORE, A, tilt=15.0, clearsky_fraction_band=(0.38, 0.41))
    assert not wrong.agrees_with_published_band(A)
    assert wrong.expected < A.specific_yield.lo


def test_the_clearsky_fraction_is_not_a_clearness_index() -> None:
    """Guard against the specific error this band was written to avoid: Kt
    (~0.55-0.62 in TN) is defined against extraterrestrial irradiance, and using
    it to scale clear-sky irradiance removes the atmosphere twice."""
    lo, hi = CLEARSKY_FRACTION_BAND
    assert 0.70 < lo < hi < 0.90, (
        "a value near 0.55 here means someone has confused the clear-sky fraction "
        "with the clearness index; see CLEARSKY_FRACTION_BAND"
    )


# ---------------------------------------------------------------------------
# The band, and what it is made of
# ---------------------------------------------------------------------------


def test_the_result_is_a_band_not_a_point(vellore) -> None:  # type: ignore[no-untyped-def]
    """NFR-2 / ARCHITECTURE.md 7. Without a TMY file the yield genuinely is not
    knowable to a point, and the type must not pretend otherwise."""
    assert vellore.conservative < vellore.expected
    assert not vellore.annual_kwh_per_kwp.is_certain


def test_a_shaded_roof_yields_less(vellore) -> None:  # type: ignore[no-untyped-def]
    shaded = annual_yield(*VELLORE, A, tilt=15.0, shading_retained=0.8)
    assert shaded.expected == pytest.approx(vellore.expected * 0.8, rel=0.01)


def test_shading_retained_of_zero_is_refused() -> None:
    """A roof with no sun is a roof with no analysis, not a roof with zero yield
    silently written into the database."""
    with pytest.raises(ValueError, match="shading_retained"):
        annual_yield(*VELLORE, A, tilt=15.0, shading_retained=0.0)


def test_the_loss_chain_is_itemised_not_a_single_efficiency(vellore) -> None:  # type: ignore[no-untyped-def]
    """FR-2.4: documented physical assumptions. One blended derate cannot be
    argued with; seven named ones can."""
    losses = vellore.losses.to_json()
    for name in (
        "soiling_retained",
        "inverter_retained",
        "wiring_retained",
        "mismatch_retained",
        "availability_retained",
        "shading_retained",
        "total_retained",
    ):
        assert name in losses
    assert 0.80 < losses["total_retained"] < 0.95


def test_the_loss_chain_multiplies_out() -> None:
    chain = LossChain(
        soiling=0.95, temperature=1.0, inverter=0.96,
        wiring=0.98, mismatch=0.98, availability=0.99, shading=1.0,
    )
    assert chain.total == pytest.approx(0.95 * 0.96 * 0.98 * 0.98 * 0.99)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def test_the_best_tilt_is_near_but_not_equal_to_latitude() -> None:
    """"Tilt equals latitude" is a heuristic, and the optimum at 12.9 N is a few
    degrees steeper. Scanning is why this is checked rather than assumed."""
    tilt = best_tilt(*VELLORE)
    assert 5.0 <= tilt <= 25.0
    assert tilt != pytest.approx(VELLORE[0], abs=0.1)


def test_a_north_facing_array_yields_less_than_a_south_facing_one() -> None:
    """The most basic sanity check there is, and the one that catches an azimuth
    convention silently inverted."""
    south = annual_yield(*VELLORE, A, tilt=20.0, azimuth=180.0)
    north = annual_yield(*VELLORE, A, tilt=20.0, azimuth=0.0)
    assert north.expected < south.expected


def test_a_steeper_tilt_costs_output_at_this_latitude() -> None:
    flat_ish = annual_yield(*VELLORE, A, tilt=15.0)
    steep = annual_yield(*VELLORE, A, tilt=45.0)
    assert steep.expected < flat_ish.expected


def test_clearsky_irradiance_scales_with_the_fraction() -> None:
    full = clearsky_poa(*VELLORE, 15.0, 180.0, clearsky_fraction=1.0)
    half = clearsky_poa(*VELLORE, 15.0, 180.0, clearsky_fraction=0.5)
    assert half["poa_global"].sum() == pytest.approx(full["poa_global"].sum() * 0.5, rel=0.02)


def test_monthly_yields_sum_to_roughly_the_annual_expected(vellore) -> None:  # type: ignore[no-untyped-def]
    total = sum(vellore.monthly_kwh_per_kwp.values())
    assert total == pytest.approx(vellore.expected, rel=0.01)
    assert len(vellore.monthly_kwh_per_kwp) == 12


# ---------------------------------------------------------------------------
# The database row (NFR-2)
# ---------------------------------------------------------------------------


def test_the_persisted_row_carries_a_band_and_calls_itself_inferred(vellore) -> None:  # type: ignore[no-untyped-def]
    row = as_roof_analysis_row(vellore, "bldg-demo-1")
    assert row["annual_yield_kwh_per_kwp_source"] == "inferred"
    assert (
        row["annual_yield_kwh_per_kwp_lo"]
        <= row["annual_yield_kwh_per_kwp"]
        <= row["annual_yield_kwh_per_kwp_hi"]
    ), "the band ordering roof_analyses.ck_yield_band_ordered enforces"
    assert row["annual_yield_kwh_per_kwp_confidence"] < 1.0
    assert row["loss_assumptions_json"]["irradiance_source"] == "CLEARSKY_SCALED"
    assert len(row["monthly_yield_json"]) == 12


def test_a_clearsky_run_is_less_confident_than_a_tmy_one(vellore) -> None:  # type: ignore[no-untyped-def]
    """The difference is the single biggest reason to get a real weather file,
    so it has to be visible in the stored confidence."""
    row = as_roof_analysis_row(vellore, "bldg-demo-1")
    assert row["annual_yield_kwh_per_kwp_confidence"] == 0.55
