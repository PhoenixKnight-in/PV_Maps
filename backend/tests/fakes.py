"""An in-memory `Repository`, so the API tests need no PostgreSQL.

This is what the Protocol in `api/repository.py` is for. The routes, the
serialisers, the optimiser and the rule packs are all exercised for real; only
the row fetch is substituted. A test suite that needed a live PostGIS container
would get skipped on the laptop where the calculation actually gets changed.
"""

from __future__ import annotations

from pvmaps.api.repository import AddressRow, BuildingRow, SizingRunRecord, YieldRow

__all__ = [
    "FakeRepository",
    "FakeResult",
    "FakeSession",
    "FakeSessionFactory",
    "building",
    "demo_address",
    "demo_building",
]


def building(
    building_id: str = "bldg-demo-1",
    *,
    roof_area_m2: float = 118.0,
    usable_area_m2: float = 84.0,
    analysis: YieldRow | None = None,
    confidence: float = 0.82,
) -> BuildingRow:
    return BuildingRow(
        id=building_id,
        geojson={
            "type": "Polygon",
            "coordinates": [
                [
                    [79.1325, 12.9202],
                    [79.1326, 12.9202],
                    [79.1326, 12.9203],
                    [79.1325, 12.9203],
                    [79.1325, 12.9202],
                ]
            ],
        },
        obstruction_geojson=None,
        roof_area_m2=roof_area_m2,
        usable_area_m2=usable_area_m2,
        typology="residential",
        confidence=confidence,
        analysis=analysis,
    )


def demo_building() -> BuildingRow:
    return building()


def demo_address() -> AddressRow:
    return AddressRow(
        id="addr-demo-1",
        display_name="12 Katpadi Road, Vellore (demo)",
        building_id="bldg-demo-1",
        lat=12.9202,
        lon=79.1325,
    )


class FakeRepository:
    """Implements `Repository` without a database.

    `fail_on_save` exists because "the calculation succeeded but the write did
    not" is a real operating state with a deliberate behaviour
    (`sizing._persist`), and a behaviour nobody can trigger is a behaviour nobody
    has tested.
    """

    def __init__(
        self,
        buildings: dict[str, BuildingRow] | None = None,
        addresses: list[AddressRow] | None = None,
        *,
        fail_on_save: bool = False,
    ) -> None:
        self.buildings = buildings if buildings is not None else {"bldg-demo-1": demo_building()}
        self.addresses = addresses if addresses is not None else [demo_address()]
        self.fail_on_save = fail_on_save
        self.saved: list[SizingRunRecord] = []
        self.search_calls: list[tuple[str, int]] = []

    async def ping(self) -> bool:
        return True

    async def search_addresses(self, q: str, limit: int) -> list[AddressRow]:
        self.search_calls.append((q, limit))
        needle = q.casefold()
        hits = [a for a in self.addresses if needle in a.display_name.casefold()]
        return hits[:limit]

    async def get_building(self, building_id: str) -> BuildingRow | None:
        return self.buildings.get(building_id)

    async def save_sizing_run(self, run: SizingRunRecord) -> None:
        if self.fail_on_save:
            raise RuntimeError("simulated database write failure")
        self.saved.append(run)


class FakeResult:
    """One scalar, which is all `/healthz` reads."""

    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class FakeSession:
    """Just enough of an AsyncSession for `/healthz`.

    `pilot_roofs=0` is the state a migrated-but-unseeded database is in, and
    `raises` is how the other two failures are reached: a `ProgrammingError`
    stands in for a database that answers without the schema, anything else for a
    database that is not answering at all.
    """

    def __init__(self, *, pilot_roofs: int = 1, raises: BaseException | None = None) -> None:
        self.pilot_roofs = pilot_roofs
        self.raises = raises

    async def execute(self, *_args: object, **_kw: object) -> FakeResult:
        if self.raises is not None:
            raise self.raises
        return FakeResult(self.pilot_roofs)

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class FakeSessionFactory:
    def __init__(
        self,
        *,
        fail: bool = False,
        pilot_roofs: int = 1,
        raises: BaseException | None = None,
    ) -> None:
        self.pilot_roofs = pilot_roofs
        self.raises = raises or (RuntimeError("simulated database outage") if fail else None)

    def __call__(self) -> FakeSession:
        return FakeSession(pilot_roofs=self.pilot_roofs, raises=self.raises)
