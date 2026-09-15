# PV Maps

**Bill-aware rooftop solar sizing for Tamil Nadu.**
*The roof is not the recommendation. The bill is.*

![Status](https://img.shields.io/badge/phase-1%20pilot-orange)
![Python](https://img.shields.io/badge/python-FastAPI-009688)
![DB](https://img.shields.io/badge/PostgreSQL-PostGIS-336791)
![Frontend](https://img.shields.io/badge/React-Vite-646CFF)
![Rules](https://img.shields.io/badge/rule%20packs-unverified-yellow)

<!-- Replace with a GIF: address → roof outline → array → comparison curve. Blur service numbers and meter readings first. -->

### PV Maps
<img width="1600" height="900" alt="WhatsApp Image 2026-09-15 at 11 53 23 PM" src="https://github.com/user-attachments/assets/fb25ca63-e261-48a5-adf7-f3b946d34f4a" />
<img width="1600" height="900" alt="WhatsApp Image 2026-09-15 at 11 54 19 PM" src="https://github.com/user-attachments/assets/1e95711b-f5db-4f9b-975e-4ca2ff04bf5c" />
<img width="1600" height="900" alt="WhatsApp Image 2026-09-15 at 11 55 20 PM" src="https://github.com/user-attachments/assets/d1d41d21-6991-4eb9-8e85-af693925e9bb" />


Most solar calculators answer *"what can this roof produce?"* and value the result at an average tariff. In Tamil Nadu, both halves of that are wrong:

- **The roof is rarely the limit.** The sanctioned load on the service connection usually is.
- **A solar kWh has no single price.** Under TN's telescopic tariff it is worth anywhere from ₹0 to the top slab rate, depending on which slab it displaces.

Give PV Maps an address and an electricity bill. It finds the roof in satellite imagery, measures it, draws the array that physically fits, and runs **every allowed system size** against your actual tariff slabs — returning a comparison curve with honest ranges instead of one confident number.

> ⚠️ **Not an official TNPDCL feasibility approval.** Tariff and subsidy rule packs are not yet verified against primary sources. Treat every rupee figure as indicative.

| Document | What it covers |
|---|---|
| [PRD.md](PRD.md) | The problem and the product argument |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design and boundaries |
| [STATUS.md](STATUS.md) | What works today, and what is still wrong |

---

## Contents

- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Repository layout](#repository-layout)
- [Engineering decisions](#engineering-decisions)
- [Privacy: confirmed connections](#privacy-confirmed-connections)
- [Known gaps and failing tests](#known-gaps-and-failing-tests)
- [Pilot dataset](#pilot-dataset)
- [Operations](#operations)
- [Phase 2](#phase-2)

---

## How it works

```mermaid
flowchart LR
    A[Address or GPS] --> B[Geocode<br/>Nominatim → Mappls]
    B --> C[Roof segmentation<br/>SAM2 on GPU]
    C --> D[Array packing<br/>setback + winter-solstice pitch]
    E[Bill: amount, units,<br/>or meter readings] --> F[Tariff engine<br/>telescopic slabs, Decimal]
    D --> G[Sizing optimiser]
    F --> G
    H[Rule packs<br/>tariff · subsidy · yield] --> G
    G --> I[Comparison curve<br/>recommended vs largest allowed]
```

1. **Locate** — Nominatim gets within ~1 km; Mappls resolves *which street it actually is*.
2. **Measure** — `POST /v1/roof-at` prompts SAM2 with the point and returns masks at three scales, each with its own array layout.
3. **Read the bill** — units per month, sanctioned load, or the rupee amount reverse-computed through the slab schedule.
4. **Size** — every candidate size up to `min(roof ceiling, sanctioned load)` is scored on import offset, export, subsidy, maintenance and payback.
5. **Explain** — the result shows which constraint binds, the recommended size against the largest allowed, and the range behind every figure.

---

## Quick start

**Prerequisites:** Docker with Compose. Live roof measurement additionally needs an NVIDIA GPU.

```bash
cp .env.example .env              # set CONNECTION_HASH_KEY — see Privacy below
docker compose up --build
```

| URL | Service |
|---|---|
| http://localhost:8080 | Web app (change `WEB_PORT` if 8080 is taken) |
| http://localhost:8000/docs | API (OpenAPI) |
| http://localhost:8100/healthz | Segmenter |

One command brings up a **working** stack, not an empty one:

| Service | Role | Lifetime |
|---|---|---|
| `postgis` | PostgreSQL 16 + PostGIS | session |
| `migrate` | `alembic upgrade head` (idempotent) | one run |
| `seed` | Rule packs + five pilot roofs (idempotent, no CUDA) | one run |
| `api` | FastAPI; starts only after seeding succeeds | session |
| `web` | Built frontend behind nginx | session |
| `segmenter` | SAM2 for live roof measurement | session |

Download the SAM2 checkpoint once:

```bash
docker compose --profile pipeline run --rm pipeline fetch-checkpoint
```

### Verify it is up

```bash
curl -s localhost:8000/healthz
```

`/healthz` reads a pilot roof rather than running `SELECT 1`, so each failure names its own fix:

| `database` | Meaning | Fix |
|---|---|---|
| `ok` | Roofs readable; browser uses the API | — |
| `not_configured` | No `DATABASE_URL`; browser uses bundled pilot data | Set `DATABASE_URL` |
| `unreachable` | Database not answering | Check `postgis` |
| `schema_missing` | Connected, not migrated | `alembic upgrade head` |
| `no_pilot_data` | Migrated, empty | Run the seeder |

Anything other than `ok` returns **503**, which tells the browser to fall back instead of waiting on lookups that cannot succeed.

<details>
<summary><b>Run without Docker</b></summary>

**Backend** — the calculation engine needs no database:

```bash
cd backend
uv sync --group dev
uv run pytest
```

Against a database:

```bash
export DATABASE_URL=postgresql+asyncpg://pvmaps:pvmaps@localhost:5432/pvmaps
uv run alembic upgrade head
uv run --group seed python -m pvmaps.pipeline.cli seed
uv run --group api uvicorn pvmaps.api.main:app --reload
```

**Web:**

```bash
cd web && npm install && npm run dev
```

</details>

---

## Repository layout

```
backend/
  sizing/      pure calculation engine: capacity, slabs, self-consumption, NPV
  segmenter/   SAM2 service for live roof measurement
  pipeline/    offline jobs: roof import, pvlib yield, array packing, IoU
  phase2/      DT-quota allocator (not wired to any Phase 1 route)
  config/      versioned rule packs (tariffs, subsidies, solar assumptions)
web/           React + Vite client
docker/        api · web · seed · pipeline images
```

---

## Engineering decisions

**Nothing regulatory is hardcoded.** Tariffs, subsidies and solar assumptions live in versioned JSON under `backend/src/pvmaps/config/`, each with an `effective_from` and a `verification_status`. Unverified packs surface as `assumptions_verified: false` and a provisional banner in the UI.

**`Decimal`, never `float`, for rupees.** Binary floats in a telescopic sum drift by paise, and the tariff engine must match a real bill to the rupee.

**Ranges, not points.** Without interval-meter data, self-consumption cannot be known. `Range` is the working type inside the sizing module and `Estimate[T]` is what crosses into the API — there is no type that can carry a bare inferred number, so honesty is enforced by the type system rather than by convention.

**Geometry in EPSG:4326, area in EPSG:32644.** UTM 44N covers Vellore; skipping the projection silently inflates every roof. Areas are always recomputed on import, never trusted from a GeoJSON property.

**No physics on the request path.** No torch, pvlib or MILP inside an HTTP handler — the offline pipeline writes rows and the API reads them. The segmenter is the one deliberate exception, and it is isolated: separate image, its own `/healthz`, and **no `depends_on` from `api`**. If it is down, one route degrades to "roof measurement unavailable" while the tariff engine and optimiser keep serving.

**The capacity cap must never exceed what physically fits.** The packed array (illustrative) and the engine's capacity ceiling (conservative area ratio) are computed independently and deliberately disagree. `test_panel_layout.py` asserts the safety ordering instead of forcing agreement: the number quoted to a household must be buildable on their roof.

**Provenance is load-bearing.** A fixture may be approximate; it may not claim a source it does not have. An early pilot coordinate was labelled `TNPDCL_GIS` at 0.98 confidence when it was really a geocoder hit on the wrong street — and that confidence suppressed the "confirm your roof" prompt that would have caught it.

<details>
<summary><b>Geocoding: two undocumented Mappls behaviours</b></summary>

Order matters. OSM does not know most Indian residential cross-streets: asked for *"3rd East Cross Road, Gandhi Nagar, Katpadi"* it returned **24th** East Cross Road — a real street, different PIN, 834 m away — with nothing flagging the substitution. So Nominatim seeds the area and Mappls decides the street.

Before editing `api/routers/locate.py`:

- **`region=IND` is mandatory.** Without it every search returns `400`.
- **`query` is capped at 45 characters.** 46 returns `400` with an empty body — so short test queries passed while real addresses failed, which looked intermittent rather than broken.

On the standard tier Mappls returns an `eLoc` but never coordinates. Position is recovered by **trilaterating** autosuggest `distance` values from four reference points around the coarse seed. Against six references: worst residual 1.1 m (street), 1.4 m (building). Solutions disagreeing with their own inputs by more than 25 m are discarded. Results are cached per `eLoc`.

</details>

<details>
<summary><b>Segmentation: the area on screen is a proposal</b></summary>

SAM2 is class-agnostic — it has no concept of "roof" and segments whatever region the point lands in. A tap on a terrace legitimately returns roof plane, building and block; in dense settlements it over-segments toward the block. The UI shows all three scales, flags areas outside 15–5,000 m², and asks the user to confirm.

Every candidate carries its own array layout. Packing is pure geometry on an existing footprint (no GPU, no imagery fetch), so switching scales redraws modules instantly.

</details>

---

## Privacy: confirmed connections

A household can pin their roof and confirm it, keyed to their EB service number so it survives restarts — **without the number ever being stored.**

- `confirmed_connections` is keyed by `HMAC-SHA256(server_key, normalised_number)`. Given a number you can find the row; given the table you cannot recover numbers.
- **HMAC, not a plain hash:** service numbers are short and structured (region, section, distribution codes from small sets), so an unkeyed SHA-256 column is brute-forceable.
- No name, address or section columns. A table of *number → rooftop* is a record of who lives where; ARCHITECTURE.md §8 forbids retaining it.
- `sizing_runs` holds confirmed consumption with no identifying field and an `expires_at`, enforced by `pipeline purge-runs`.
- Uploaded bills are parsed to fill the form, then discarded.

Generate the key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

| `CONNECTION_HASH_KEY` | Effect |
|---|---|
| empty | Persistence disabled; confirmations last until restart |
| set | Confirmations persist |
| **changed** | **Every stored rooftop is orphaned.** Do not rotate casually. |

An unknown service number returns `404`, not a guess. Mapping numbers to service points requires TNPDCL's registry, and there is no feed to it.

---

## Known gaps and failing tests

These are red on purpose. A green suite that has never seen a real bill would be worse than a red one.

| Test / metric | Passes when |
|---|---|
| `test_five_real_bills_are_present` | `backend/tests/fixtures/bills/real_bills.json` holds five real, PII-stripped bills |
| `test_schedule_is_verified_against_primary_source` | The TNERC tariff order is checked and the schedule marked verified |
| Segmentation IoU (PRD §10) | 50 hand-drawn held-out roofs exist to measure against |

The IoU tool already exists and exits non-zero below target:

```bash
docker compose --profile pipeline run --rm pipeline iou \
    --predicted /data/predicted.geojson --truth /data/hand-drawn.geojson
```

Until the ground truth exists, the honest figure is **"not measured"** — not an estimate borrowed from a paper about a different city.

Also not yet modelled: TN net-metering export credit (exported units are valued at ₹0), per-roof pvlib yield for live roofs (regional band used instead), obstruction deduction on live roofs, and the distribution network.

---

## Pilot dataset

Five hand-corrected Vellore roofs form the reference set — the only roofs with hand-checked areas and their own pvlib yield band. Each rehearses a different answer:

| Address | Bill scenario | What it demonstrates |
|---|---|---|
| 12 Katpadi Road | 565 units/mo, home part of the day | 7.0 kWp roof capped at 3 kW by contract; a smaller system still recommended |
| 4 Gandhi Nagar | 95 units/mo, empty weekdays | The honest zero — nothing to save on the free slab |
| VIT Technology Tower | none | Physical potential only; no rupee figure without VIT's tariff |
| 9 Thorapadi Main Road | 780 units/mo, daytime-heavy, daytime EV | The roof binds first (water tank and stairhead marked) |
| 7 Sathuvachari 5th Cross | 130 units/mo, home all day | `MARGINAL` — pays back only on the optimistic bound |

Defined once in `pipeline/seed.PILOT_ROOFS`; both the database seeder and the browser's offline bundle are generated from it, so they cannot drift.

---

## Operations

The `pipeline` image carries CUDA and torch and is **not** part of the default stack.

```bash
# Import hand-drawn roofs (areas recomputed in EPSG:32644)
docker compose --profile pipeline run --rm pipeline roofs-import \
    --footprints /data/ward-2.geojson \
    --obstructions /data/ward-2-obstructions.geojson --dry-run

# Compute per-roof pvlib yield bands for imported roofs
docker compose --profile pipeline run --rm pipeline yield

# Delete expired sizing runs (safe on a schedule)
docker compose --profile pipeline run --rm pipeline purge-runs

# Full CLI
docker compose --profile pipeline run --rm pipeline --help
```

---

## Phase 2

`backend/src/pvmaps/phase2/` contains the distribution-transformer quota allocator — built, tested (12 passing), and reachable from **no** Phase 1 route. It needs authorised TNPDCL network data that does not exist yet. The Phase 1 API exposes no transformer, quota or allocation endpoint, and the UI never labels a network estimate "verified" without a source and version. See ARCHITECTURE.md §11.

---

## Contributing

1. Read [STATUS.md](STATUS.md) before picking up work.
2. Never commit bill data containing PII — see the `_README` block in the bills fixture.
3. Rule-pack changes need a source citation and an `effective_from` date.
4. Run `uv run pytest` and `npm run build` before opening a PR.
