"""Array layout — the picture a household is shown of their own roof.

The number this produces is checked against `sizing.capacity`'s
`area_per_kwp_m2` band rather than asserted on its own. Two independent routes
to "how much fits" that disagree would mean the map and the recommendation are
describing different arrays, and the map is the one a person will believe.
"""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

pytest.importorskip("shapely", reason="pipeline group")

from shapely.geometry import Polygon  # noqa: E402

from pvmaps.pipeline.layout import PanelSpec, pack_panels  # noqa: E402
from pvmaps.pipeline.roofs import area_m2, usable_roof  # noqa: E402

VELLORE_LAT = 12.9241
VELLORE_LON = 79.1358


def square_roof(side_m: float, lat: float = VELLORE_LAT, lon: float = VELLORE_LON) -> Polygon:
    h = side_m / 2 / 111_320.0
    w = side_m / 2 / (111_320.0 * math.cos(math.radians(lat)))
    return Polygon([(lon - w, lat - h), (lon + w, lat - h), (lon + w, lat + h), (lon - w, lat + h)])


def test_panels_stay_inside_the_usable_roof() -> None:
    """FR-1.2: a panel drawn over a parapet or an obstruction is a lie in the
    most direct possible form -- the household can see it."""
    geom = usable_roof(square_roof(12.0))
    layout = pack_panels(geom.usable, latitude_deg=VELLORE_LAT)

    assert layout.count > 0
    for panel in layout.panels:
        assert geom.usable.contains(panel.buffer(-1e-9)), "a module escaped the usable roof"


def test_the_engine_never_promises_more_capacity_than_actually_fits() -> None:
    """The safety property, and the reason the layout must NOT drive capacity.

    `sizing.capacity.roof_max_kwp` divides usable area by the HI bound of
    `area_per_kwp_m2` (12 m2/kWp), which is the conservative direction for a cap.
    A real packing is denser than that, so the cap always understates what fits.
    That ordering is what must hold: the number quoted to a household is
    reachable on their actual roof.

    Measured 2026-09-14, the packed density is NOT inside the pack's 9-12 band
    and gets further outside it as roofs grow -- 10.1 m2/kWp on a 10 m roof, 7.3
    on a 30 m one, because edge waste shrinks proportionally. That is a real
    divergence, not a tuning error, and it is why the array drawn on the map is
    illustrative geometry while the kWp figure stays with the tested engine.
    """
    from pvmaps.sizing.assumptions import load_assumptions
    from pvmaps.sizing.capacity import roof_max_kwp

    a = load_assumptions()
    for side in (10.0, 14.0, 20.0):
        geom = usable_roof(square_roof(side))
        packed = pack_panels(geom.usable, latitude_deg=VELLORE_LAT)
        cap = float(roof_max_kwp(Decimal(str(area_m2(geom.usable))), a))

        assert packed.kwp >= cap, (
            f"{side} m roof: the engine caps at {cap:.2f} kWp but only "
            f"{packed.kwp:.2f} kWp of modules physically fit -- the cap is "
            f"promising a system that cannot be built"
        )


def test_row_pitch_grows_as_you_leave_the_tropics() -> None:
    """Winter noon sun is lower further from the equator, so rows must spread.

    A pitch that ignored latitude would look fine in Vellore and shade every
    back row in Delhi, which is exactly the kind of error that survives a demo.
    """
    spec = PanelSpec()
    assert spec.row_pitch_m(12.9) < spec.row_pitch_m(28.6)  # Vellore < Delhi


def test_a_roof_too_small_for_a_setback_packs_nothing() -> None:
    """`usable_roof` returns an empty plane below twice the setback. Packing that
    must yield zero panels rather than raising -- a stairwell head is a real roof
    and a real answer of 'nothing fits'."""
    geom = usable_roof(square_roof(0.8))
    layout = pack_panels(geom.usable, latitude_deg=VELLORE_LAT)
    assert layout.count == 0
    assert layout.kwp == 0


def test_rows_follow_the_roof_not_true_north() -> None:
    """A grid aligned to north wastes a triangle along every edge of a rotated
    roof. The bearing is taken from the roof's own longest edge."""
    from shapely.affinity import rotate

    straight = usable_roof(square_roof(14.0)).usable
    turned = rotate(straight, 30.0, origin=straight.centroid)

    a = pack_panels(straight, latitude_deg=VELLORE_LAT)
    b = pack_panels(turned, latitude_deg=VELLORE_LAT)

    # Same roof, same area, so a rotation must not cost a meaningful number of
    # modules. Allowing one is for the edge cells the rotation reshuffles.
    assert abs(a.count - b.count) <= 1
