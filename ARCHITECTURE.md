# PV Maps — Web Application Architecture

**Status:** v1.1 · **Backs:** [PRD.md](PRD.md) · **Owner:** Parthiban

> PV Maps is a responsive web application. The browser delivers the product; the backend performs auditable calculations; offline jobs prepare roof and yield data.

---

## 1. Architecture decision

Phase 1 is a web application for the Bill-to-Roof Optimiser.

The product flow is:

~~~text
Address → roof result → bill details → recommended solar size → value curve
~~~

The application must be usable in a desktop browser for the judge demo and on a phone browser for bill upload and quick inputs. It is not a native Android, iOS, Flutter, or desktop application.

The system has two planes:

| Plane | Responsibility | Runs when |
|---|---|---|
| Offline preparation | Roof segmentation, obstruction correction, solar-yield calculation, pilot-address indexing | Before demo or when pilot imagery changes |
| Web request path | Search, roof lookup, bill confirmation, sizing calculation, results rendering | Every browser session |

The request path must not load SAM2, run a GPU model, or create a new roof mask. It only reads precomputed roof data and calculates the bill-specific recommendation.

---

## 2. System diagram

~~~text
OFFLINE PREPARATION
Google/Bhuvan imagery + irradiance assumptions
             │
             ▼
  Python pipeline
  SAM2 + roof review + pvlib
             │
             ▼
PostgreSQL + PostGIS
buildings · roof_analyses · addresses · tariff_schedules
             │
             │ HTTPS / JSON
             ▼
WEB APPLICATION
┌─────────────────────────────────────────────────────────────────┐
│ Browser: React + JavaScript + Vite                              │
│                                                                 │
│ Address search → MapLibre map → roof correction                 │
│ Bill form / optional upload → daytime-use form                  │
│ Results panel → savings curve → assumptions and disclaimer      │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
                     FastAPI calculation API
                 search · roof result · bill extract
                 sizing run · dated tariff rules
                               │
                               ▼
                     PostgreSQL + PostGIS

PHASE 2 ONLY
TNPDCL-authorised service/DTR/feeder/application data
                               │
                               ▼
                         Grid Passport
~~~

---

## 3. Web application stack

| Layer | Choice | Reason |
|---|---|---|
| Web frontend | React, JavaScript, Vite | Fast browser delivery, familiar web tooling, and no native-app build/release step |
| UI | Tailwind CSS plus accessible headless components | Responsive layout without a custom design system |
| Map | MapLibre GL JS | High-quality browser map, GeoJSON roof overlays, and direct control of map styling |
| Charts | Recharts | Clear sizing-versus-savings and payback curves |
| Form validation | React Hook Form and Zod | Bill fields are critical calculation inputs and must be visible and editable |
| API | FastAPI and Pydantic v2 | Typed calculation contract and automatic OpenAPI documentation |
| Database | PostgreSQL 16 with PostGIS | Stores address geometry, roof geometry, results, and versioned configuration in one system |
| Roof/yield pipeline | Python, SAM2, rasterio, shapely, pvlib | Runs offline only; no computer vision dependency reaches browser requests |
| Calculation engine | Python Decimal-based tariff library plus deterministic sizing optimiser | Auditable financial calculations; no opaque recommendation model |
| Deployment | Static web hosting plus containerised API and PostGIS | The frontend deploys independently and can be cached aggressively |
| Local demo | Docker Compose | One command starts API, database, and web server for an offline-safe demo |

No native mobile framework is part of Phase 1. The responsive web layout is the mobile strategy.

---

## 4. Frontend architecture

~~~text
web/
├── src/
│   ├── pages/
│   │   ├── HomePage.jsx
│   │   └── ResultsPage.jsx
│   ├── components/
│   │   ├── AddressSearch.jsx
│   │   ├── RoofMap.jsx
│   │   ├── RoofCorrection.jsx
│   │   ├── BillInputForm.jsx
│   │   ├── DaytimeUseForm.jsx
│   │   ├── SizingCurve.jsx
│   │   ├── EconomicsBreakdown.jsx
│   │   ├── AssumptionsPanel.jsx
│   │   └── GridDisclosure.jsx
│   ├── api/
│   │   └── client.ts
│   ├── schemas/
│   │   └── sizing.ts
│   └── styles/
│       └── globals.css
└── public/
    └── demo-fallback/
        └── pilot-addresses.json
~~~

### 4.1 Primary browser flow

1. **AddressSearch** finds a precomputed pilot address.
2. **RoofMap** shows imagery and the extracted roof polygon.
3. **RoofCorrection** lets the user adjust the outline or obstruction assumptions for the demo.
4. **BillInputForm** accepts a bill upload or confirmed manual values.
5. **DaytimeUseForm** asks occupancy, daytime loads, and expected new loads.
6. The browser calls the sizing API.
7. **ResultsPage** renders:
   - roof maximum;
   - sanctioned-load maximum;
   - recommended kWp;
   - self-consumed and exported solar;
   - savings and payback ranges;
   - dated assumptions; and
   - the required official-feasibility disclosure.

### 4.2 Responsive layout

| Screen | Layout |
|---|---|
| Desktop and tablet | Map and roof details on the left; bill inputs/results on the right; sizing curve below |
| Phone | Address and map first; bill form second; result card and curve last |
| Demo display | Full-width map with a fixed recommendation panel and large before/after values |

The first useful interaction is always address search. No login wall appears before the roof result.

### 4.3 Browser bill handling

The calculation spine must work without document extraction:

- Manual bill entry is always available.
- A text-based PDF can be parsed in the browser when possible.
- If the user uploads a photograph or scanned bill, the web application sends it to the optional extraction endpoint.
- Returned values are populated into editable fields; the user confirms them before any sizing calculation.
- The original upload is discarded after extraction unless retention is explicitly requested.

This keeps OCR as convenience, not product logic.

---

## 5. Backend architecture

~~~text
backend/
├── src/pvmaps/
│   ├── api/
│   │   ├── routes_search.py
│   │   ├── routes_roofs.py
│   │   ├── routes_sizing.py
│   │   └── routes_bill_extract.py
│   ├── tariff/
│   │   ├── schedule.py
│   │   └── engine.py
│   ├── sizing/
│   │   ├── profiles.py
│   │   ├── self_consumption.py
│   │   └── optimise.py
│   ├── db/
│   │   ├── models.py
│   │   └── session.py
│   ├── pipeline/
│   │   ├── roofs.py
│   │   ├── ingest.py
│   │   ├── seed.py
│   │   └── yield_physics.py
│   └── config/
│       ├── tariffs/
│       ├── subsidies/
│       └── solar_assumptions/
├── tests/
│   ├── test_tariff.py
│   ├── test_tariff_golden.py
│   ├── test_sizing.py
│   └── test_api.py
└── pyproject.toml
~~~

### 5.1 Pure calculation modules

The modules below must have no database, HTTP, browser, or filesystem dependency after configuration is loaded:

| Module | Responsibility |
|---|---|
| Tariff engine | Reconstruct bill charges from tariff rules and entered consumption |
| Self-consumption model | Convert yield and daytime-use profile into self-used and exported energy ranges |
| Sizing optimiser | Evaluate every allowed candidate kWp and choose the best-value option |
| Subsidy calculator | Apply dated subsidy and cost assumptions |

Use Decimal for rupee arithmetic. Do not use binary floating-point values for bill calculations.

### 5.2 API surface

~~~text
GET  /v1/search?q=                   Pilot-address search
GET  /v1/buildings/{id}              Roof geometry, usable area, yield assumptions
POST /v1/sizing-runs                 Confirmed bill profile + roof id → recommendation
POST /v1/bill-extract                Optional temporary PDF/image extraction
GET  /v1/tariffs/current             Current dated rule summary for UI disclosure
GET  /healthz                        Health check

PHASE 2 ONLY
POST /v2/grid-passports              Consent-based official service lookup
GET  /v2/grid-passports/{id}         Dated Grid Passport result
POST /v2/grid-passports/{id}/apply   Official application handoff
~~~

The Phase 1 API has no transformer, quota, allocation, or grid-eligibility endpoint.

---

## 6. Data model

~~~sql
addresses(
  id, normalized_address, display_name, geom, search_vector
)

buildings(
  id, address_id, geom, roof_area_m2, usable_area_m2,
  obstruction_geojson, typology, confidence, analysed_at
)

roof_analyses(
  id, building_id, annual_yield_kwh_per_kwp,
  monthly_yield_json, loss_assumptions_json, version
)

tariff_schedules(
  id, category, version, effective_from, effective_to, rules_json
)

subsidy_schedules(
  id, category, version, effective_from, effective_to, rules_json
)

sizing_runs(
  id, building_id, tariff_version, input_profile_json,
  roof_max_kwp, sanctioned_load_max_kwp, recommended_kwp,
  self_consumed_kwh_range_json, exported_kwh_range_json,
  savings_range_json, payback_range_years, created_at
)
~~~

A bill upload is not the source of truth. The confirmed profile submitted to the sizing endpoint is the calculation input. Persist only the minimum confirmed values needed for a user-requested result.

Phase 2 adds separate tables for consented service references, utility data snapshots, Grid Passport status, and official application references.

---

## 7. Calculation request path

~~~text
1. Browser requests a roof result by address.
2. API returns precomputed roof geometry, usable area, and yield range.
3. User confirms bill fields and daytime-use assumptions.
4. Browser sends those values to POST /v1/sizing-runs.
5. API:
   a. obtains the dated tariff and subsidy schedules;
   b. calculates roof and sanctioned-load limits;
   c. evaluates candidate sizes from 0.5 kWp to the feasible maximum;
   d. estimates self-consumption and export for each candidate;
   e. calculates annual savings and payback ranges;
   f. returns the best-value size plus the entire comparison curve.
6. Browser renders the recommendation and its assumptions.
~~~

The API must return ranges whenever the bill lacks interval-meter data. It must never represent a self-consumption estimate as an observed fact.

---

## 8. Privacy and security

- Use HTTPS in deployed environments.
- Validate all form data with matching Zod browser schemas and Pydantic API schemas.
- Limit bill-extraction requests by IP and size.
- Process uploaded bills in memory and discard them after extraction by default.
- Do not log consumer numbers, names, addresses, bill images, or raw OCR output.
- Encrypt any retained confirmed profile at rest.
- Use a short-lived, opaque sizing-run identifier rather than exposing database identifiers.
- Do not add authentication in Phase 1 unless retaining user history becomes a deliberate requirement.

---

## 9. Deployment and demo resilience

### 9.1 Development and local demonstration

~~~text
Docker Compose
├── postgis   PostgreSQL + PostGIS
├── migrate   alembic upgrade head          (one shot, idempotent)
├── seed      rule packs + pilot roofs      (one shot, idempotent)
├── api       FastAPI, started after seed
└── web       Vite build served by Nginx

Offline preparation is a separate command or profile:
└── pipeline  Python + CV/physics dependencies
~~~

`up` must produce a working stack, not an empty database, so schema and pilot
data are services rather than instructions in a README. Both are idempotent: a
step that cannot be re-run is a step nobody dares run the night before a demo.

`migrate` runs from the api image, which already carries alembic and asyncpg.
`seed` runs from a third, small image (`docker/seed.Dockerfile`) holding psycopg
and typer: the seeder writes with the synchronous driver, which the api image does
not have, and requiring the CUDA pipeline image to write fifteen rows would put
the demo database behind a multi-gigabyte build.

The pipeline is never started during a judging demo.

### 9.2 Hosted deployment

- Serve the compiled frontend as static assets through a CDN or static-hosting provider.
- Run the FastAPI service as a container.
- Use managed PostgreSQL with PostGIS, or the Docker database for the hackathon demo.
- Configure CORS to permit only the web application's deployed origin.
- Cache precomputed roof responses by building identifier.

### 9.3 Demo fallback

Keep the validated pilot addresses, roof results, and bill profiles bundled into the local demo environment. If external geocoding or imagery fails, the web app still demonstrates the full Bill-to-Roof calculation from its local pilot data.

The bundle is generated from the same `PILOT_ROOFS` the database seeder writes and serialised through the same Pydantic models the live routes use, so it cannot describe a different building or a different result shape. It carries each roof's footprint as GeoJSON: a fallback that cannot draw the roof is not the flow the product is judged on.

---

## 10. Build order

1. Build the pure tariff engine and verify five known baseline bills.
2. Build the pure sizing optimiser and test its roof/sanctioned-load invariants.
3. Seed one hand-corrected roof and one representative bill profile.
4. Build the FastAPI sizing endpoint.
5. Build the responsive web result screen without a live map.
6. Add address search and MapLibre roof view.
7. Add bill upload and optional extraction.
8. Add segmentation pipeline and grow the pilot area.
9. Add the optional Synthetic Grid Pressure research view only after the core acceptance criteria pass.

This order guarantees a working web application even if the imagery pipeline or map polish slips.

---

## 11. Phase 2 boundary — Grid Passport

Grid Passport requires source-backed TNPDCL data:

- consumer service to DTR mapping;
- DTR capacity and feeder constraints;
- commissioned rooftop solar;
- live or dated rooftop-solar applications and approvals; and
- the applicable TNERC/TNPDCL rule version.

Phase 2 introduces a utility-integration adapter behind the API. It does not alter the Bill-to-Roof calculation engine, except that a verified grid limit may become an additional upper bound after official data is available.

~~~text
Phase 1 recommendation
= minimum(roof maximum, sanctioned-load maximum, economic optimum)

Phase 2 recommendation
= Phase 1 recommendation, checked against a source-backed Grid Passport
~~~

No browser component may call an electrical network estimate “verified” unless the API returns an authorised source, timestamp, and policy version.
