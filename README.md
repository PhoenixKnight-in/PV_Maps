# PV Maps

Grid-aware rooftop solar sizing for Tamil Nadu.

Most solar calculators answer *"what can this roof produce?"* and value the
answer at an average tariff. Both halves are wrong here. TN roofs are rarely the
binding constraint — the sanctioned load on the service connection usually is —
and TN's telescopic tariff means a solar kWh is worth anywhere from ₹0 to
₹11.55 depending on which slab it displaces.

- **[PRD.md](PRD.md)** — the problem and the product argument
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — the system design

---

## Layout

```
backend/     FastAPI + the pure calculation engine
web/         React + Vite browser application
docker/      api · web · pipeline images
```

---

## Quick start

Everything, in Docker:

```bash
docker compose up --build
```

Then open <http://localhost:8080>. The API is on <http://localhost:8000>, docs at
`/docs`.

That one command brings up a *working* stack, not an empty one. In order:

| Service | What it does | Lives for |
|---|---|---|
| `postgis` | PostgreSQL 16 + PostGIS | the session |
| `migrate` | `alembic upgrade head` | one run |
| `seed` | rule packs and the five pilot roofs | one run |
| `api` | FastAPI, started only once seeding succeeded | the session |
| `web` | the built frontend behind nginx | the session |

`migrate` and `seed` are idempotent, so they run on every `up`. `seed` is a small
image (`docker/seed.Dockerfile`): psycopg and typer, no CUDA, because recreating
the demo database should not require building a multi-gigabyte image to write
fifteen rows.

The `pipeline` service is deliberately **not** in the default set — it carries
CUDA and torch, and ARCHITECTURE.md 9.1 says it is never started during a demo.
Run it explicitly:

```bash
docker compose --profile pipeline run --rm pipeline --help
```

### Is it actually up?

```bash
curl -s localhost:8000/healthz
```

`/healthz` counts pilot roofs rather than running `SELECT 1`, so it distinguishes
the states that matter and names each one after its fix:

| `database` | Meaning |
|---|---|
| `ok` | a roof can be read; the browser uses the API |
| `not_configured` | no `DATABASE_URL`; the browser uses its bundled pilot data |
| `unreachable` | the database is not answering |
| `schema_missing` | it is answering, but `alembic upgrade head` has not run |
| `no_pilot_data` | migrated and empty; the seeder has not run |

Everything but `ok` answers 503, which is what tells the browser to fall back
(ARCHITECTURE.md 9.3) instead of waiting on roof lookups that cannot succeed.

### Backend, without Docker

```bash
cd backend
uv sync --group dev
uv run pytest
```

The calculation engine needs no database. To run the API against one:

```bash
export DATABASE_URL=postgresql+asyncpg://pvmaps:pvmaps@localhost:5432/pvmaps
uv run alembic upgrade head
uv run --group seed python -m pvmaps.pipeline.cli seed
uv run --group api uvicorn pvmaps.api.main:app --reload
```

### Web, without Docker

```bash
cd web
npm install
npm run dev
```

---

## The two tests that are supposed to fail

`backend/tests/test_tariff_golden.py` fails on a fresh clone. That is deliberate
and it should stay that way until someone does the work:

| Test | Passes when |
|---|---|
| `test_five_real_bills_are_present` | `backend/tests/fixtures/bills/real_bills.json` holds 5 real TANGEDCO bills |
| `test_schedule_is_verified_against_primary_source` | The TNERC order has been read and the schedule JSON marked verified |

The tariff engine is the only component a judge can falsify from the audience
with a paper bill and a phone, and PRD 8.1 requires it to match **to the rupee**.
A green suite that has never seen a real bill would be worse than a red one.

Strip PII before committing any bill data — see the `_README` block inside that
fixture file.

### The third number nobody can report yet

PRD 10 also asks for segmentation IoU on 50 held-out roofs, **reporting the actual
number**. The measurement exists and exits non-zero below target:

```bash
docker compose --profile pipeline run --rm pipeline iou \
    --predicted /data/predicted.geojson --truth /data/hand-drawn.geojson
```

What does not exist is the 50 hand-drawn roofs to measure against. Until someone
draws them, the honest statement is "not measured" — not an estimate, and not a
number borrowed from a paper about a different city.

---

## The pilot area

Five hand-corrected roofs in Vellore, which is the number PRD 10's end-to-end
criterion names. Each one is there to rehearse a different answer, because a demo
that can only show the happy case is not demonstrating the product:

| Address | Bill scenario | What it shows |
|---|---|---|
| 12 Katpadi Road | 565 units/mo, someone home part of the day | The reveal: a 7.0 kWp roof capped at 3 kW by the contract, and a smaller system still recommended |
| 4 Gandhi Nagar | 95 units/mo, empty on weekdays | The honest zero. On the free slab there is nothing to save |
| VIT Technology Tower | *none* | Physical potential only. No rupee figure until VIT's own tariff and consumption are known (PRD 11) |
| 9 Thorapadi Main Road | 780 units/mo, daytime-heavy, EV charged by day | The roof binding first, on a small roof with a hand-marked water tank and stairhead |
| 7 Sathuvachari 5th Cross | 130 units/mo, home all day | `MARGINAL` — pays back on the optimistic bound and not the pessimistic one |

They are defined once, in `pipeline/seed.PILOT_ROOFS`, and both the database
seeder and the browser's offline bundle are built from that tuple. The bundle
cannot describe a different building from the one the API serves.

### Growing it

New roofs arrive as GeoJSON somebody drew over imagery, not as edits to a Python
tuple:

```bash
docker compose --profile pipeline run --rm pipeline roofs-import \
    --footprints /data/ward-2.geojson \
    --obstructions /data/ward-2-obstructions.geojson --dry-run
```

Areas are recomputed in EPSG:32644 on import and never read from the file — a
`roof_area_m2` property in a GeoJSON was computed by whatever drew it, in whatever
CRS that tool used. Drop `--dry-run` to write, then run `yield` so those roofs get
their own pvlib band instead of the regional fallback.

### Expiring what a household told us

`sizing_runs` rows hold a confirmed monthly consumption and no identifying field.
They carry an `expires_at`, which was a promise until something read it:

```bash
docker compose --profile pipeline run --rm pipeline purge-runs
```

Safe on a schedule, safe during a demo.

---

## Rule packs

Nothing regulatory is hardcoded (NFR-4). Everything lives in versioned JSON
under `backend/src/pvmaps/config/`:

```
tariffs/            TANGEDCO slab schedules, with effective_from
subsidies/          PM Surya Ghar tiers and caps
solar_assumptions/  yield, cost, degradation, servable-fraction bands
```

Each carries a `verification_status`. They currently all read
`UNVERIFIED_AGAINST_PRIMARY_SOURCE`, the API reports that as
`assumptions_verified: false`, and the results screen shows a provisional
banner because of it. **Do not quote a rupee figure to a real household until
those are checked against primary sources.**

---

## Conventions worth knowing before you edit

**Decimal, never float, for anything in rupees.** PRD 8.1 requires rupee-exact
output; a binary float in a telescopic sum will cost a paisa and there is no
arguing that away on stage.

**Ranges, not points.** Without an interval meter, self-consumption genuinely
cannot be known — so `Range` is the working type of the sizing module and
`Estimate[T]` is what crosses into the API. There is no type available that can
carry a bare inferred number, which is how NFR-2 is enforced rather than merely
intended. Differences (export, headroom) cross their bounds; see
`self_consumption.py`.

**Geometry in EPSG:4326, area in EPSG:32644.** UTM 44N covers Vellore. Skipping
the transform silently inflates every roof area.

**The request path does no physics.** No torch, no pvlib, no MILP behind an HTTP
handler. The offline pipeline writes rows; the API reads them.

---

## Phase 2

`backend/src/pvmaps/phase2/` holds the DT-quota allocator — built, tested
(12 passing), and reachable from no Phase 1 route. It needs authorised TNPDCL
data that does not exist yet; ARCHITECTURE.md 11 is the boundary. The Phase 1
API has no transformer, quota, or allocation endpoint, and the UI must never
call an electrical-network estimate "verified" without a source and a version.
