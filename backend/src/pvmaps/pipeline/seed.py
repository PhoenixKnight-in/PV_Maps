"""Seed the database — ARCHITECTURE.md 10 item 3.

    "Seed one hand-corrected roof and one representative bill profile."

Two jobs:

1. **Mirror the rule packs** into `tariff_schedules` and `subsidy_schedules`. The
   JSON files stay the source of truth — they version with the code and the pure
   engine reads them without a database. These rows exist so a `sizing_run` can
   record which rules produced it, which is ARCHITECTURE.md 6's reproducibility
   requirement.

2. **Load the pilot roofs** into `addresses`, `buildings` and `roof_analyses`.
   PRD 9: "Precompute all roof data. Do not run segmentation live on stage."

Uses the SYNCHRONOUS psycopg driver, deliberately. This is a batch write in the
offline plane; the async pool exists for the request path and borrowing it here
would mean the seeder shared a connection limit with the API it is seeding.

Idempotent throughout. A seeder that cannot be run twice is a seeder nobody dares
run the night before a demo.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pvmaps.addressing import normalize_address
from pvmaps.sizing.assumptions import load_assumptions, load_subsidy
from pvmaps.tariff.schedule import CONFIG_DIR, available_versions, load_schedule

__all__ = [
    "PilotRoof",
    "polygon_wkt_to_geojson",
    "purge_expired_runs",
    "seed_all",
    "seed_pilot",
    "seed_rule_packs",
]

_PKG_ROOT = Path(__file__).resolve().parents[1]
_SUBSIDY_DIR = _PKG_ROOT / "config" / "subsidies"


@dataclass(frozen=True, slots=True)
class PilotRoof:
    """One hand-corrected demo roof.

    `usable_area_m2` is the hand-corrected figure, not a segmentation output.
    PRD 12 lists flat-roof segmentation error as a known risk and the mitigation
    is exactly this: correct the demo roofs by hand and report IoU honestly
    elsewhere, rather than hoping the model behaves on stage.
    """

    id: str
    display_name: str
    lat: float
    lon: float
    footprint_wkt: str
    """POLYGON in EPSG:4326."""

    roof_area_m2: float
    usable_area_m2: float
    typology: str
    confidence: float
    ward: str | None = None
    obstruction_geojson: dict[str, Any] | None = None

    @property
    def building_id(self) -> str:
        """`addr-<slug>` names the address; `bldg-<slug>` names the roof on it.

        A prefix swap rather than a substring replace: an id like
        `addr-addaikalam-street` contains "addr" twice, and replacing both would
        produce a building id nothing else in the system agrees with.
        """
        return f"bldg-{self.id.removeprefix('addr-')}"

    def __post_init__(self) -> None:
        if self.usable_area_m2 > self.roof_area_m2:
            raise ValueError(
                f"{self.id}: usable {self.usable_area_m2} m2 exceeds footprint "
                f"{self.roof_area_m2} m2 (buildings.ck_usable_within_roof)"
            )


# A square roughly `side_m` on a side, centred on (lat, lon). Good enough for a
# pilot fixture: the AREA columns are hand-measured figures, not derived from this
# polygon, so the outline only has to be in the right place and the right rough
# size for the map to look correct.
def _ring(lat: float, lon: float, side_m: float) -> list[tuple[float, float]]:
    half_lat = (side_m / 2) / 111_320.0
    # Longitude degrees shrink with latitude; at 12.92 deg N the factor is ~0.974.
    half_lon = (side_m / 2) / (111_320.0 * math.cos(math.radians(lat)))
    return [
        (lon - half_lon, lat - half_lat),
        (lon + half_lon, lat - half_lat),
        (lon + half_lon, lat + half_lat),
        (lon - half_lon, lat + half_lat),
        (lon - half_lon, lat - half_lat),
    ]


def _square(lat: float, lon: float, side_m: float) -> str:
    coords = ", ".join(f"{x:.7f} {y:.7f}" for x, y in _ring(lat, lon, side_m))
    return f"POLYGON(({coords}))"


def polygon_wkt_to_geojson(wkt: str) -> dict[str, Any]:
    """`POLYGON((lon lat, ...))` → the GeoJSON PostGIS would hand back.

    The database serves `ST_AsGeoJSON(b.geom)` and the browser draws whatever it
    gets. The offline demo bundle (ARCHITECTURE.md 9.3) has to draw the same
    outline, and it is built on a laptop with no PostGIS and no shapely — so the
    one conversion that both paths need lives here, in the module that owns the
    WKT, rather than being approximated a second time by the bundle script.

    Deliberately strict, and only about the single-ring polygons the pilot
    actually holds: a silently mis-parsed outline is a roof drawn in the wrong
    place, which is worse than a crash at build time.
    """
    body = wkt.strip()
    if not body.upper().startswith("POLYGON"):
        raise ValueError(f"not a POLYGON: {wkt[:32]!r}")
    body = body[body.index("(") :].strip()
    if not (body.startswith("((") and body.endswith("))")):
        raise ValueError(f"only single-ring POLYGON WKT is supported: {wkt[:32]!r}")

    ring = []
    for pair in body[2:-2].split(","):
        parts = pair.split()
        if len(parts) != 2:
            raise ValueError(f"expected 'lon lat' pairs, got {pair.strip()!r}")
        ring.append([float(parts[0]), float(parts[1])])

    if len(ring) < 4 or ring[0] != ring[-1]:
        raise ValueError("a polygon ring must be closed and have at least three corners")
    return {"type": "Polygon", "coordinates": [ring]}


def _obstructions(
    lat: float, lon: float, *marks: tuple[float, float, float, str]
) -> dict[str, Any]:
    """Hand-marked obstructions, in the shape `RoofGeometry.obstruction_geojson`
    produces — FR-1.2 and FR-1.6.

    The pipeline writes this structure from segmented geometry; a hand-corrected
    pilot roof writes it from a person looking at the imagery. Both end up in the
    same column and reach the browser through the same field, so they have to have
    the same shape, and the `label` is what lets the UI explain WHY a usable area
    is smaller than a footprint — FR-1.5 requires the assumption to be
    correctable, and an unexplained subtraction cannot be argued with.

    Each mark is placed as `(north_m, east_m, side_m, label)` relative to the roof
    centre, in metres. Degrees would put a typo's worth of obstruction outside the
    roof it is supposed to sit on.
    """
    features = []
    for north_m, east_m, side_m, label in marks:
        c_lat = lat + north_m / 111_320.0
        c_lon = lon + east_m / (111_320.0 * math.cos(math.radians(lat)))
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[x, y] for x, y in _ring(c_lat, c_lon, side_m)]],
                },
                "properties": {"area_m2": round(side_m * side_m, 2), "label": label},
            }
        )
    return {"type": "FeatureCollection", "features": features}


PILOT_ROOFS: tuple[PilotRoof, ...] = (
    PilotRoof(
        id="addr-demo-1",
        display_name="12 Katpadi Road, Vellore (demo)",
        lat=12.9202,
        lon=79.1325,
        footprint_wkt=_square(12.9202, 79.1325, 10.9),
        roof_area_m2=118.0,
        usable_area_m2=84.0,
        typology="residential",
        confidence=0.82,
        ward="Vellore-ward-1",
    ),
    PilotRoof(
        id="addr-demo-2",
        display_name="4 Gandhi Nagar, Vellore (demo, free-slab household)",
        lat=12.9241,
        lon=79.1358,
        footprint_wkt=_square(12.9241, 79.1358, 9.8),
        roof_area_m2=96.0,
        usable_area_m2=71.0,
        typology="residential",
        confidence=0.79,
        ward="Vellore-ward-1",
    ),
    PilotRoof(
        id="addr-demo-3",
        display_name="VIT Vellore, Technology Tower (demo, physical potential only)",
        lat=12.9692,
        lon=79.1559,
        footprint_wkt=_square(12.9692, 79.1559, 44.0),
        roof_area_m2=1940.0,
        usable_area_m2=1310.0,
        typology="institutional",
        confidence=0.68,
        ward="Katpadi",
    ),
    PilotRoof(
        id="addr-demo-4",
        display_name="9 Thorapadi Main Road, Vellore (demo, daytime-heavy on a small roof)",
        lat=12.9021,
        lon=79.1410,
        footprint_wkt=_square(12.9021, 79.1410, 7.9),
        roof_area_m2=62.0,
        usable_area_m2=34.0,
        typology="residential",
        confidence=0.74,
        ward="Vellore-ward-1",
        obstruction_geojson=_obstructions(
            12.9021,
            79.1410,
            (2.2, 2.2, 1.4, "water tank"),
            (-1.6, -2.0, 2.2, "stairhead"),
        ),
    ),
    PilotRoof(
        id="addr-demo-5",
        display_name="7 Sathuvachari 5th Cross, Vellore (demo, home all day, low units)",
        lat=12.9440,
        lon=79.1515,
        footprint_wkt=_square(12.9440, 79.1515, 10.2),
        roof_area_m2=104.0,
        usable_area_m2=76.0,
        typology="residential",
        confidence=0.81,
        ward="Vellore-ward-2",
    ),
)
"""Five roofs, which is the number PRD 10's end-to-end criterion names, and each
one is in the pilot to rehearse a different answer:

| Roof | Rehearses |
|---|---|
| demo-1 | The PRD 11 reveal: the contract caps a roof that could hold twice as much |
| demo-2 | PRD G2's honest zero -- a free-slab household is told not to buy |
| demo-3 | VIT: physical potential only, and no rupee figure at all |
| demo-4 | The roof binding first, on a small roof with hand-marked obstructions |
| demo-5 | MARGINAL -- pays back on the optimistic bound and not the pessimistic one |

The third is a deliberate trap to avoid. PRD 11: for VIT, show "estimated
physical rooftop potential" only. There is no bill profile seeded for it, and
PRD 10 is explicit that no rupee figure may be attached to its roof until VIT's
actual tariff, sanctioned demand and consumption are known. The API will happily
size it if someone POSTs a sanctioned load -- which is correct behaviour for a
confirmed profile, and is why the constraint is stated here rather than enforced
by a missing row.

The fourth carries obstruction geometry because a usable area that is 55% of its
footprint is the figure a judge is most likely to challenge, and FR-1.6 requires
the reason to be persisted rather than folded into a number."""


def _rows_to_upsert(table: str, rows: list[dict[str, Any]], key: tuple[str, ...]) -> str:
    columns = list(rows[0])
    placeholders = ", ".join(f"%({c})s" for c in columns)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c not in key)
    return (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(key)}) DO UPDATE SET {updates}"
    )


def seed_rule_packs(conn: Any) -> dict[str, int]:
    """Mirror config/tariffs and config/subsidies into their tables.

    `rules_json` is the whole file, verbatim. Storing a parsed subset would make
    the row and the file disagree the moment the schema grows a field, and the row
    exists precisely so that a past result can be explained.
    """
    tariffs = []
    for version in available_versions():
        schedule = load_schedule(version)
        raw = _read_pack(CONFIG_DIR, version)
        tariffs.append(
            {
                "id": f"tariff:{schedule.category}:{schedule.version}",
                "category": schedule.category,
                "version": schedule.version,
                "effective_from": schedule.effective_from,
                "effective_to": raw.get("effective_to"),
                "rules_json": json.dumps(raw),
                "verification_status": schedule.verification_status,
            }
        )

    subsidies = []
    for path in sorted(_SUBSIDY_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        subsidy = load_subsidy(str(raw["version"]))
        subsidies.append(
            {
                "id": f"subsidy:{raw.get('category', 'DOMESTIC')}:{subsidy.version}",
                "category": str(raw.get("category", "DOMESTIC")),
                "version": subsidy.version,
                "effective_from": subsidy.effective_from,
                "effective_to": raw.get("effective_to"),
                "rules_json": json.dumps(raw),
                "verification_status": subsidy.verification_status,
            }
        )

    with conn.cursor() as cur:
        if tariffs:
            cur.executemany(
                _rows_to_upsert("tariff_schedules", tariffs, ("category", "version")), tariffs
            )
        if subsidies:
            cur.executemany(
                _rows_to_upsert("subsidy_schedules", subsidies, ("category", "version")), subsidies
            )
    conn.commit()
    return {"tariff_schedules": len(tariffs), "subsidy_schedules": len(subsidies)}


def _read_pack(directory: Path, version: str) -> dict[str, Any]:
    for path in sorted(directory.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("version") == version or path.stem == version:
            return raw  # type: ignore[no-any-return]
    raise FileNotFoundError(f"no pack {version!r} in {directory}")


def seed_pilot(conn: Any, roofs: tuple[PilotRoof, ...] = PILOT_ROOFS) -> dict[str, int]:
    """Load pilot addresses and hand-corrected roofs.

    `normalized_address` goes through `pvmaps.addressing.normalize_address`, the
    same function `GET /v1/search` matches against. Two copies of that folding
    would drift, and the symptom is a pilot address that cannot be found mid-demo.
    """
    addresses = [
        {
            "id": r.id,
            "normalized_address": normalize_address(r.display_name),
            "display_name": r.display_name,
            "geom_wkt": f"POINT({r.lon} {r.lat})",
            "ward": r.ward,
        }
        for r in roofs
    ]
    buildings = [
        {
            "id": r.building_id,
            "address_id": r.id,
            "geom_wkt": r.footprint_wkt,
            "roof_area_m2": r.roof_area_m2,
            "usable_area_m2": r.usable_area_m2,
            "obstruction_geojson": (
                None if r.obstruction_geojson is None else json.dumps(r.obstruction_geojson)
            ),
            "typology": r.typology,
            "confidence": r.confidence,
            "analysed_at": datetime.now(UTC),
        }
        for r in roofs
    ]

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO addresses (id, normalized_address, display_name, geom, ward)
            VALUES (%(id)s, %(normalized_address)s, %(display_name)s,
                    ST_GeomFromText(%(geom_wkt)s, 4326), %(ward)s)
            ON CONFLICT (id) DO UPDATE SET
                normalized_address = EXCLUDED.normalized_address,
                display_name = EXCLUDED.display_name,
                geom = EXCLUDED.geom,
                ward = EXCLUDED.ward
            """,
            addresses,
        )
        cur.executemany(
            """
            INSERT INTO buildings (
                id, address_id, geom, roof_area_m2, usable_area_m2,
                obstruction_geojson, typology, confidence, analysed_at
            ) VALUES (
                %(id)s, %(address_id)s, ST_GeomFromText(%(geom_wkt)s, 4326),
                %(roof_area_m2)s, %(usable_area_m2)s,
                CAST(%(obstruction_geojson)s AS jsonb),
                %(typology)s, %(confidence)s, %(analysed_at)s
            )
            ON CONFLICT (id) DO UPDATE SET
                address_id = EXCLUDED.address_id,
                geom = EXCLUDED.geom,
                roof_area_m2 = EXCLUDED.roof_area_m2,
                usable_area_m2 = EXCLUDED.usable_area_m2,
                obstruction_geojson = EXCLUDED.obstruction_geojson,
                typology = EXCLUDED.typology,
                confidence = EXCLUDED.confidence,
                analysed_at = EXCLUDED.analysed_at
            """,
            buildings,
        )
    conn.commit()
    return {"addresses": len(addresses), "buildings": len(buildings)}


def write_roof_analysis(conn: Any, row: dict[str, Any]) -> None:
    """Insert or replace one `roof_analyses` row.

    Keyed on (building_id, version): re-running the same model version overwrites,
    a new version adds a row. Old rows are kept so a figure already shown to a
    user stays explicable after the model moved on (NFR-4).
    """
    payload = {
        **row,
        "monthly_yield_json": json.dumps(row.get("monthly_yield_json")),
        "loss_assumptions_json": json.dumps(row.get("loss_assumptions_json")),
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO roof_analyses (
                id, building_id, version,
                annual_yield_kwh_per_kwp,
                annual_yield_kwh_per_kwp_lo,
                annual_yield_kwh_per_kwp_hi,
                annual_yield_kwh_per_kwp_source,
                annual_yield_kwh_per_kwp_confidence,
                monthly_yield_json, loss_assumptions_json
            ) VALUES (
                %(id)s, %(building_id)s, %(version)s,
                %(annual_yield_kwh_per_kwp)s,
                %(annual_yield_kwh_per_kwp_lo)s,
                %(annual_yield_kwh_per_kwp_hi)s,
                %(annual_yield_kwh_per_kwp_source)s,
                %(annual_yield_kwh_per_kwp_confidence)s,
                CAST(%(monthly_yield_json)s AS jsonb),
                CAST(%(loss_assumptions_json)s AS jsonb)
            )
            ON CONFLICT (building_id, version) DO UPDATE SET
                annual_yield_kwh_per_kwp = EXCLUDED.annual_yield_kwh_per_kwp,
                annual_yield_kwh_per_kwp_lo = EXCLUDED.annual_yield_kwh_per_kwp_lo,
                annual_yield_kwh_per_kwp_hi = EXCLUDED.annual_yield_kwh_per_kwp_hi,
                annual_yield_kwh_per_kwp_source = EXCLUDED.annual_yield_kwh_per_kwp_source,
                annual_yield_kwh_per_kwp_confidence =
                    EXCLUDED.annual_yield_kwh_per_kwp_confidence,
                monthly_yield_json = EXCLUDED.monthly_yield_json,
                loss_assumptions_json = EXCLUDED.loss_assumptions_json
            """,
            payload,
        )
    conn.commit()


PURGE_EXPIRED_RUNS_SQL = """
DELETE FROM sizing_runs
WHERE expires_at IS NOT NULL AND expires_at < now()
"""
"""ARCHITECTURE.md 8: the sizing-run id is short-lived.

`sizing_runs.expires_at` is written on every run and indexed, and until this
existed nothing ever read it -- which made "it expires" a comment rather than a
behaviour. The rows carry no consumer number, name or address (there is no column
for one), but a household's monthly consumption is still theirs, and NFR-1 is
about what is kept rather than only about what is logged.

Deleting rather than anonymising: an expired run has no remaining purpose. The
result it explained was shown once, to one browser, days ago.
"""


def purge_expired_runs(conn: Any) -> int:
    """Delete sizing runs past their expiry. Returns how many went.

    `now()` is the database's clock, deliberately: the rows were stamped with it
    too, so a pipeline container with a skewed clock cannot delete a run that has
    not expired or keep one that has.
    """
    with conn.cursor() as cur:
        cur.execute(PURGE_EXPIRED_RUNS_SQL)
        deleted = cur.rowcount
    conn.commit()
    return int(deleted)


def seed_all(conn: Any) -> dict[str, int]:
    counts = seed_rule_packs(conn)
    counts.update(seed_pilot(conn))

    a = load_assumptions()
    if not a.is_verified:
        # The seeder is the last place someone looks before a demo, so this is a
        # good place to say it out loud.
        counts["_unverified_packs"] = 1
    return counts
