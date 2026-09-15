# PV Maps — Project Status

> **Last updated:** 2026-09-15 IST  
> **Stack health:** All 4 containers running and healthy

---

## 1. What PV Maps Does

PV Maps is a **grid-aware rooftop solar sizing platform for Tamil Nadu**. Unlike generic solar calculators that answer "what can this roof produce?", PV Maps answers **"what can this bill use?"** — because in Tamil Nadu:

- The **sanctioned load** (on the service connection) usually binds before the roof does.
- The **TNERC telescopic tariff** means a solar kWh is worth anywhere from ₹0 to ₹11.55 depending on which slab it displaces.

The platform takes an electricity bill and a rooftop, runs a full optimisation across every allowed system size, and returns a comparison curve with honest ranges rather than single-point estimates.

---

## 2. Architecture Overview

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Frontend   │     │   Backend    │     │  Segmenter   │     │   PostGIS    │
│ React + Vite │────▶│   FastAPI    │────▶│  SAM2 (GPU)  │     │  PostgreSQL  │
│  :8081       │     │  :8000       │     │  :8100       │     │  :5432       │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

| Layer | Technology | Role |
|---|---|---|
| **Frontend** | React 18, Vite, MapLibre GL, Zod | Workstation UI — address search, roof map, bill entry, results |
| **API** | FastAPI, Pydantic, asyncpg, Alembic | Sizing engine, bill parser, geocoding proxy, location resolver |
| **Segmenter** | SAM2 (Hiera Small), PyTorch, CUDA | Live roof measurement from satellite imagery |
| **Database** | PostgreSQL 16 + PostGIS 3.4 | Pilot roofs, rule packs, sizing run history |
| **Pipeline** | Offline-only profile | Roof import, pvlib yield analysis, IoU measurement |

---

## 3. Running Services

| Container | Status | Port | Health |
|---|---|---|---|
| `pvmaps-web-1` | ✅ Up ~2 hours | `localhost:8081` → `:80` | — |
| `pvmaps-api-1` | ✅ Up ~2 hours (healthy) | `localhost:8000` | `/healthz` OK |
| `pvmaps-segmenter-1` | ✅ Up ~6 hours (healthy) | `localhost:8100` | `/healthz` OK |
| `pvmaps-postgis-1` | ✅ Up ~6 hours (healthy) | `localhost:5432` | `pg_isready` OK |

**How to access:**
- Web UI: <http://localhost:8081>
- API docs: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/healthz>

---

## 4. Implemented Features

### 4.1 Roof Measurement

| Feature | Status | Details |
|---|---|---|
| 5 seeded pilot roofs (Vellore) | ✅ Complete | Pre-checked areas + pvlib yield bands |
| Live roof segmentation (anywhere) | ✅ Complete | SAM2 GPU inference via `/v1/roof-at` |
| Satellite tile fetching + caching | ✅ Complete | 3×3 tile grid at zoom 19 |
| Multi-candidate roof selection | ✅ Complete | User picks from SAM2 candidates |
| Manual roof area correction | ✅ Complete | Override input with `usable_area_source` tracking |
| Interactive map (pan/click to segment) | ✅ Complete | MapLibre GL with GeoJSON overlays |

### 4.2 Bill Intelligence

| Feature | Status | Details |
|---|---|---|
| Bill PDF/image upload + OCR extraction | ✅ Complete | Server-side text extraction → regex parsing |
| Manual entry (always available) | ✅ Complete | Units, sanctioned load, all fields editable |
| TNEB consumer ID extraction | ✅ Complete | Service Connection No (12-digit), Section, Circle, Distribution |
| Meter readings extraction | ✅ Complete | Final, Initial, MF → `(final - initial) × MF` |
| Energy charges / subsidy breakdown | ✅ Complete | Energy Charges, Govt Subsidy, Net Payable parsed |
| Bill amount → units (TNERC slab reversal) | ✅ Complete | 3-tier priority: Meter Readings → Energy Charges → Bill Amount |
| Bimonthly → monthly conversion | ✅ Complete | Auto-detection + halving with warnings |
| Tariff category detection (Domestic/Commercial) | ✅ Complete | LT-IA / LT-V regex + UI toggle |

**Consumption derivation priority (bill_parse.py):**
1. **Priority 1 — Meter Readings:** `(final_reading - initial_reading) × multiplying_factor` → `METER_READINGS`
2. **Priority 2 — Energy Charges Reversal:** `calculate_units_from_amount(energy_charges - subsidy)` → `ENERGY_CHARGES_REVERSE`
3. **Priority 3 — Bill Amount Reversal:** `calculate_units_from_amount(net_payable)` → `BILL_AMOUNT_REVERSE`

### 4.3 Geocoding & Location Resolution

| Feature | Status | Details |
|---|---|---|
| Address search (free-text) | ✅ Complete | Nominatim for the coarse seed → Mappls for street identity + trilaterated position (see 7.2) |
| Mappls OAuth2 integration | ✅ Complete | Token caching, auto-refresh, Search + Geocode endpoints |
| Indian address variant broadening | ✅ Complete | Building/care-of stripping, suffix ungluing (nagar/puram/colony) |
| GPS "Use My Location" button | ✅ Complete | Browser Geolocation API with high accuracy |
| Interactive roof pin (tap/drag) | ✅ Complete | Click anywhere on map to segment that point |

### 4.4 4-Level Location Architecture

| Level | Source | Status | Details |
|---|---|---|---|
| **Level 1** | TNPDCL GIS Lookup | ✅ Complete | `PILOT_CONNECTIONS` + `CONFIRMED_CONNECTIONS` in-memory |
| **Level 2** | Meter Repository | ✅ Complete | Same pool, keyed by `meter_number` |
| **Level 3** | Multi-component Geocoding | ✅ Complete | Address + Confidence Scorer (0–100 scale) |
| **Level 4** | User GPS / Map Pin Confirm | ✅ Complete | Haversine distance check, confirmation persistence |

**Confidence scoring breakdown:**
- Building match: +40 pts
- Street match: +25 pts
- Locality match: +15 pts
- PIN code match: +10 pts
- TNPDCL Section match: +10 pts
- Auto-accept threshold: ≥ 85%

**Pilot connection seeded:**
- `08-211-019-1233` → Meter `1773876` → `(12.95390°N, 79.14870°E)` (rooftop, ~144 m²)

### 4.5 Sizing Engine

| Feature | Status | Details |
|---|---|---|
| Full optimiser (exhaustive curve) | ✅ Complete | Every 0.5 kWp increment from minimum to feasible max |
| Slab-aware bill savings | ✅ Complete | TNERC domestic 8-slab + commercial 2-slab |
| Self-consumption split (ranges) | ✅ Complete | Occupancy × modifiers, honest `Range` bounds |
| Net metering export credit | ✅ Complete | Separate line item per FR-4.3 |
| PM Surya Ghar subsidy | ✅ Complete | Tiered by capacity (1–3 kWp brackets) |
| NPV + payback calculation | ✅ Complete | Pessimistic bound → `null` payback when it never pays back |
| Verdict classification | ✅ Complete | `RECOMMENDED` / `MARGINAL` / `NOT_ECONOMIC` / `NO_CAPACITY` |
| Binding constraint identification | ✅ Complete | `ROOF` / `SANCTIONED_LOAD` / `BOTH` |

### 4.6 Frontend UI

| Feature | Status | Details |
|---|---|---|
| Workstation layout (canvas + rails) | ✅ Complete | Map left, inputs right, consistent with results page |
| Step progress indicator (1–4) | ✅ Complete | Locate → Bill → Daytime → Size |
| Measured roof panel (live SAM2) | ✅ Complete | Candidate cards with areas, plausibility badges |
| Roof analysis panel (seeded) | ✅ Complete | Yield source, obstruction ledger, confidence |
| Bill input form with OCR pre-fill | ✅ Complete | All fields editable, "From bill" badges |
| Bill amount → units calculator | ✅ Complete | Inline with Domestic/Commercial toggle |
| Meter consumption breakdown card | ✅ Complete | Final, Initial, MF × Delta display |
| Financial breakdown bar | ✅ Complete | Energy, Subsidy, Net |
| 4-Level location card | ✅ Complete | Level badge, confidence %, score tags, GPS distance check |
| TNEB connection card | ✅ Complete | Section, Circle, Distribution, Consumer No. inputs |
| "Fly map to bill address" | ✅ Complete | Via `runLocationResolution` → `selectAddress` |
| "Verify with My GPS" button | ✅ Complete | Triggers Geolocation API, re-runs resolution with GPS |
| "Confirm Location" button | ✅ Complete | Persists coordinates via `/v1/locate/confirm` |
| Daytime use form | ✅ Complete | Occupancy profile + modifiers (EV, AC, etc.) |
| Results page | ✅ Complete | Recommended system, comparison curve, financial detail |
| Offline/fallback mode | ✅ Complete | Bundled pilot data when API is unreachable |
| Demo fallback bundle | ✅ Complete | Pre-computed scenarios for 5 pilot roofs |

---

## 5. API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Stack health — counts pilot roofs |
| `GET` | `/v1/search?q=` | Pilot-address search (seeded table) |
| `GET` | `/v1/geocode?q=` | Free-text geocoding (Mappls → Nominatim) |
| `GET` | `/v1/buildings/{id}` | Retrieve a seeded building's geometry + yield |
| `POST` | `/v1/roof-at` | Live roof segmentation (SAM2 GPU proxy) |
| `POST` | `/v1/bill-extract` | OCR + regex extraction from uploaded bill |
| `POST` | `/v1/sizing-runs` | Run the full optimiser, return recommendation |
| `GET` | `/v1/tariffs/current` | Current TNERC slab schedule |
| `POST` | `/v1/locate/resolve` | 4-Level location resolution |
| `POST` | `/v1/locate/confirm` | User-confirmed coordinates persistence |

---

## 6. Key Files Modified During This Session

| File | What Changed | Why |
|---|---|---|
| [`schemas.py`](backend/src/pvmaps/api/schemas.py) | `SizingRequest.model_config` changed to `extra="ignore"` | Prevented 422 errors when extra bill metadata fields are sent alongside sizing inputs |
| [`bill_parse.py`](backend/src/pvmaps/api/bill_parse.py) | Added meter readings, energy charges, subsidy parsing; 3-tier consumption derivation | Accurate unit extraction priority: meter > charges reversal > bill amount reversal |
| [`locate.py`](backend/src/pvmaps/api/routers/locate.py) | Added 4-Level Location Architecture, confidence scorer, haversine distance check | Replaced single geocode with hierarchical resolution (TNPDCL GIS → Meter → Geocoding → User GPS) |
| [`client.ts`](web/src/api/client.ts) | Added `resolveLocation`, `confirmLocation` methods and TypeScript interfaces | Frontend API client for 4-Level location system |
| [`HomePage.jsx`](web/src/pages/HomePage.jsx) | Fixed `ReferenceError: bid is not defined`; added location resolution flow, GPS, confirm handlers | Fixed "Could not calculate" error; integrated 4-level location into main flow |
| [`BillInputForm.jsx`](web/src/components/BillInputForm.jsx) | Added TNEB connection card, meter breakdown, financial summary, location card, bill calculator | Full bill intelligence UI with interactive location verification |

---

## 7. Bugs Fixed During This Session

### 7.1 "Could not calculate a recommendation. Please try again"

**Root causes (two separate bugs):**

1. **FastAPI 422 Unprocessable Entity** — `SizingRequest` had `extra="forbid"` in its Pydantic config. When the frontend sent extra bill metadata fields (consumer_number, section, etc.) alongside sizing inputs, FastAPI rejected the entire request.  
   **Fix:** Changed to `extra="ignore"` so unrecognised fields are silently dropped.

2. **JavaScript ReferenceError: `bid` is not defined** — In `HomePage.jsx`, the variable `bid` was used on line 291 but never declared with `const bid = parsed.data.building_id`.  
   **Fix:** Added the declaration and sanitised the sizing payload to send only calculation-relevant fields.

### 7.2 Map Landed 834 m From the Address (fixed 2026-09-15)

**Symptom:** the pilot connection resolved to a roof ~850 m from the real one.
Reported against Google Maps, which put the household beside Sunbreeze
Apartments on 3rd East Cross Road.

**Four defects in one chain:**

1. **Mappls `region=IND` was never sent.** Every `/places/search` call returned
   `400 Bad Request`, so the "primary" geocoder (4.3) contributed *nothing*
   and every lookup silently fell through to Nominatim.
2. **Mappls caps `query` at 45 characters.** Undocumented; bisected 2026-09-15
   (45 -> 200, 46 -> 400 with an empty body). Real addresses exceed it -- the
   failing one is 48 chars -- so even with `region` fixed, ordinary lookups
   failed while short test queries passed. That is why it read as flaky.
3. **OSM has no low-numbered East Cross Roads in Katpadi.** Asked for *3rd*,
   Nominatim answers *24th* -- a real street, different PIN (632006 vs 632007),
   834 m away -- with nothing in the response marking the substitution.
4. **The confidence scorer credited it as a street match.** `any(token in name)`
   matched on the word "east", so a wrong street scored 25/25.

**Root cause of the bad fixture:** `PILOT_CONNECTIONS` held that Nominatim hit,
nudged by hand until SAM2 returned a believable roof, labelled `TNPDCL_GIS` at
`0.98` confidence. No GIS extract was ever involved. Because it claimed 0.98 it
set `requires_user_confirmation=False`, so the household was never offered the
pin-correction UI that would have caught it.

**Fixes:**

- `region=IND` sent; queries trimmed to 45 chars on word boundaries, dropping
  redundant tail components (`India`, `Tamil Nadu`) before the street.
- **Mappls coordinates recovered by trilateration.** This plan returns an
  `eLoc` but never a lat/lon (`/nearby` 401s, `advancedmaps/geo_code` 412s).
  Autosuggest's `distance` field is the exception, so position is solved from
  distances to four reference points. Verified against six references: worst
  residual **1.1 m** (street) and **1.4 m** (building). Cached per eLoc.
- Order inverted: **OSM for the coarse seed, Mappls for which street it is.**
- Scorer requires the distinguishing tokens; an ordinal conflict (3rd vs 24th)
  is disqualifying outright.
- Fixture corrected to `12.959108, 79.143165`, `source: MAPPLS_STREET`,
  `confidence: 0.55`, `accuracy_meters: 150`, `geocode_level: street` -- so it
  now *requires* confirmation and the household can move the pin.

**Result:** the failing query now returns 3rd East Cross Road, Bharathi Nagar
**1 m** from the independently trilaterated truth (was 834 m).

> A fixture may be approximate. It may not claim a provenance it does not have.

### 7.3 Panel Array Never Drew on the Map (fixed 2026-09-15)

The segmenter returned a correct layout (32 modules, 12.8 kWp, 213 m² usable)
and the side panel displayed the counts, but no modules appeared on the map.

**Cause:** every layer effect in `RoofMap.jsx` guarded with
`if (m.isStyleLoaded()) draw(); else m.once("load", draw)`. Both branches are
wrong. `load` fires once per map lifetime, so registering `once("load")` after
it has fired never runs; and `isStyleLoaded()` is not a latch -- it returns
false again whenever a source is loading. Panels arrive in the same response as
the candidate outlines, so the layout effect hit that window every time: the
outlines drew, the modules never did.

**Fix:** `whenStyleReady(m, fn)` resolves on `styledata`/`idle`, re-checks
`isStyleLoaded()`, unsubscribes, and returns a cleanup. Applied to all four
effects. Verified live: `panel-fill`, `panel-line`, `usable-line` present with
66 rendered features.

### 7.4 Locating by Service Connection Number (2026-09-15)

**Asked:** a service number is unique, so use it to locate the household.

**Why uniqueness is not enough:** a unique key only locates someone if you hold
the registry mapping it to a service point. That registry is TNPDCL's and PV
Maps has no feed to it (10, "Real TNPDCL API integration"). Two consequences
were addressed:

1. **An unknown number no longer guesses.** It used to fall through to Level 3
   and build the query `", Vellore, Tamil Nadu"` -- which geocodes perfectly
   well, to the middle of Vellore, and was returned with a confidence score.
   It now returns 404 saying there is no TNPDCL lookup and asking for the bill
   address or a map pin.
2. **A confirmed rooftop now survives a restart.** `CONFIRMED_CONNECTIONS` was
   an in-memory dict (10, first item), so every confirmation was lost on
   restart and only the one seeded connection ever resolved.

**Storage shape -- the number is NOT retained.** ARCHITECTURE.md 8 forbids
retaining consumer numbers, and a table of (service number -> rooftop) is
precisely a record of which household lives at which roof. So
`confirmed_connections` is keyed by `HMAC-SHA256(server key, normalised
number)`:

- Given the number you can find the row; given the table you cannot recover
  numbers. There is no `consumer_name`, `address` or `section` column.
- **HMAC, not plain SHA-256.** A TNEB number is short and heavily structured,
  so an unsalted digest of every possible number is cheap to precompute. The
  key is what makes the digest useless on its own.
- **`CONNECTION_HASH_KEY` must be configured and stable.** Empty disables
  persistence outright; *changing it orphans every stored rooftop* while still
  appearing to work.
- `08-211-019-1233`, `08 211 019 1233` and `082110191233` are one connection.
  Meter number is hashed the same way, so either identifier resolves.

Verified across a full container rebuild: confirm a rooftop, rebuild the API,
then both the service number and the meter number alone return it at level 4.

> A lookup needs something that MATCHES a number, not something that IS one.

**One trap worth recording:** the first implementation wrote rows correctly and
read none back. asyncpg raised `AmbiguousParameterError` -- a parameter used
only beside `IS NOT NULL` gives the driver nothing to infer a type from -- and a
blanket `except Exception` turned that into a silent "no rows". Fixed with
explicit `CAST(... AS text)`, and both handlers now log.

### 7.5 Panel Array Did Not Follow the Selected Scale (fixed 2026-09-15)

Tapping a different candidate changed the area and the outline but left the
previous scale's modules on the roof, and the "panels that fit" figure with
them.

**Cause:** `layout` was computed for the chosen candidate ONLY and returned at
the top level of the response. The original reasoning -- that three arrays at
once would be unreadable -- confused *producing* a layout with *drawing* one;
the client draws exactly one.

**Fix:** every `Candidate` carries its own `layout`. Packing is pure geometry on
an already-segmented footprint (no GPU, no imagery fetch), so the extra
candidates cost milliseconds. `RoofMap` and `MeasuredRoofPanel` both read the
selected candidate's layout. Verified: 241 m² -> 33 panels / 13.2 kWp, tapping
158 m² -> 22 panels / 8.8 kWp with the rectangles redrawn.

### 7.6 Results Page Aligned Around an Empty Grid (fixed 2026-09-15)

The results screen only has a map when the roof came from a seeded pilot
building. A roof measured live has no `building`, so `canvas` was null and
`Workstation` drew its blueprint placeholder: a featureless ruled rectangle
holding open the widest column on the page while the findings were pushed into
two narrow rails either side of it.

**Fix:** no canvas means no middle column, not an empty one. `Workstation` now
renders a single centred `max-w-5xl` column with the rails in sequence, and the
Economics/Assumptions pair below it matches the column count above it.

### 7.7 Wrong Roof Selected (1,375 m² road strip instead of residential rooftop)

**Root cause:** Nominatim's geocode for "24th East Cross Road" returned the road's geographic centroid `(12.95465°N, 79.14868°E)`. SAM2 segmenter, given a road-surface point, correctly segmented the road pavement boundary (1,375 m²) instead of a rooftop.

**Fix:** Updated `PILOT_CONNECTIONS["08-211-019-1233"]` coordinates from street centroid to actual rooftop at `(12.95390°N, 79.14870°E)`, which SAM2 segments as the residential roof (~144 m²).

---

## 8. Configuration

### Environment Variables (`.env`)

| Variable | Value | Purpose |
|---|---|---|
| `POSTGRES_*` | `pvmaps` | PostGIS database credentials |
| `API_PORT` | `8000` | FastAPI backend |
| `WEB_PORT` | `8081` | Frontend (8080 taken by Oracle listener) |
| `CORS_ALLOW_ORIGINS` | `localhost:8081,localhost:5173` | Allowed origins |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Frontend → API connection |
| `MAPPLS_CLIENT_ID` | Set ✅ | MapmyIndia OAuth2 client |
| `MAPPLS_CLIENT_SECRET` | Set ✅ | MapmyIndia OAuth2 secret |
| `MAPPLS_REST_KEY` | Set ✅ | MapmyIndia REST fallback key |
| `CONNECTION_HASH_KEY` | Set ✅ (gitignored) | HMAC key for `confirmed_connections`. **Changing it orphans every stored rooftop**; empty disables persistence. |

### Mappls (MapmyIndia) Integration

- **OAuth2 flow:** Client credentials → access token → cached with auto-refresh
- **Endpoints used:**
  1. `atlas.mappls.com/api/places/search/json` (primary, building-level)
  2. `atlas.mappls.com/api/places/geocode` (fallback, street-level)
- **Fallback:** If Mappls yields no results or credentials are absent, Nominatim OSM is used

---

## 9. Rule Packs & Verification Status

| Pack | Location | Verified? |
|---|---|---|
| TNERC Tariff Schedule | `backend/src/pvmaps/config/tariffs/` | ⚠️ `UNVERIFIED_AGAINST_PRIMARY_SOURCE` |
| PM Surya Ghar Subsidy | `backend/src/pvmaps/config/subsidies/` | ⚠️ `UNVERIFIED_AGAINST_PRIMARY_SOURCE` |
| Solar Assumptions (yield, cost) | `backend/src/pvmaps/config/solar_assumptions/` | ⚠️ `UNVERIFIED_AGAINST_PRIMARY_SOURCE` |

> **Warning:** The results screen shows a "provisional" banner because of this. Do not quote rupee figures to real households until these are checked against primary TNERC/MNRE sources.

---

## 10. Known Limitations & Open Items

### Not Yet Implemented

| Item | Priority | Notes |
|---|---|---|
| Persistent TNPDCL GIS database | Medium | Confirmed rooftops now persist in `confirmed_connections`, keyed by HMAC (see 7.4). `PILOT_CONNECTIONS` remains an in-memory seed fixture. |
| Real TNPDCL API integration | High | Level 1/2 currently uses hardcoded pilot data; needs authorized API access |
| Segmentation IoU measurement | Medium | 50 hand-drawn truth roofs needed for PRD 10 metric |
| Rule pack verification | Medium | Tariff, subsidy, assumptions all need primary source check |
| Phase 2 DT-quota allocator | Low | Built and tested (12 passing) but unreachable from Phase 1 routes |
| 5 real bill test fixtures | Low | `test_five_real_bills_are_present` intentionally fails |

### Known Gotchas

1. **Mappls geocoding** — Standard tier may not return lat/lon for all queries; the system automatically falls back to Nominatim.
2. **Nominatim rate limiting** — 1 req/s policy enforced with `asyncio.sleep(1.1)` between variant attempts.
3. **SAM2 cold start** — First segmentation after container start takes ~20–60 seconds (model loading + tile cache miss).
4. **Indian address quirks** — Building names, care-of prefixes, and glued suffixes (Gandhinagar vs Gandhi Nagar) are all handled by the variant broadening engine but edge cases may exist.
5. **Bimonthly billing** — TN bills are bimonthly; the system auto-detects and halves but warns the user to verify.

---

## 11. How to Test the Full Flow

1. **Hard refresh** the browser at <http://localhost:8081> (`Ctrl + Shift + R`)
2. **Search an address** — type "Gandhi Nagar Katpadi Vellore" or click anywhere on the map
3. **Upload a bill** or manually enter:
   - Units consumed per month: `285`
   - Sanctioned load: `3` kW
4. **Or use the bill amount calculator:** Enter ₹2620 → auto-computes 569 bi-monthly → 285 monthly
5. **Select occupancy** and any modifiers (EV, AC, etc.)
6. **Click "Size this roof against the bill"**
7. **View results:** Recommended system size, comparison curve, financial breakdown

### Test the Pilot Connection

1. Upload the sample bill PDF (service connection `08-211-019-1233`)
2. The TNEB connection card auto-fills: Section, Circle, Consumer No.
3. Click "Locate Connection on Map" → Level 1 TNPDCL GIS lookup → 98% confidence
4. Map flies to the correct rooftop at `(12.95390°N, 79.14870°E)`
5. SAM2 segments ~144 m² residential roof

---

## 12. Commands Reference

```bash
# Start the full stack
docker compose up --build

# Check health
curl -s http://localhost:8000/healthz | python -m json.tool

# View logs
docker compose logs -f api
docker compose logs -f segmenter

# Rebuild and restart a single service
docker compose up --build --force-recreate api
docker compose up --build --force-recreate web

# Run backend tests
cd backend && uv run pytest

# Run frontend dev server (hot reload)
cd web && npm run dev

# Pipeline (offline, needs GPU)
docker compose --profile pipeline run --rm pipeline --help
```

---

## 13. Project Structure

```
PV_Maps/
├── backend/
│   └── src/pvmaps/
│       ├── api/                    # FastAPI application
│       │   ├── bill_parse.py       # Bill text → structured fields (regex, no ML)
│       │   ├── schemas.py          # Pydantic wire contract
│       │   └── routers/
│       │       ├── locate.py       # Geocoding + 4-Level location resolver
│       │       ├── sizing.py       # Optimiser endpoint
│       │       ├── buildings.py    # Building lookup
│       │       ├── search.py       # Pilot address search
│       │       ├── bill_extract.py # OCR text extraction route
│       │       └── tariffs.py      # TNERC tariff disclosure
│       ├── config/                 # Versioned rule packs (tariffs, subsidies, assumptions)
│       ├── sizing/                 # Pure calculation engine (optimise, capacity, profiles)
│       ├── tariff/                 # Slab billing logic
│       ├── segmenter/              # SAM2 inference service
│       ├── pipeline/               # Offline: seed, import, yield, IoU
│       ├── phase2/                 # DT-quota allocator (future)
│       └── db/                     # SQLAlchemy models, Alembic migrations
├── web/
│   └── src/
│       ├── api/                    # API client + data source (live/fallback)
│       ├── components/             # React components (BillInputForm, RoofMap, etc.)
│       ├── pages/                  # HomePage, ResultsPage
│       ├── schemas/                # Zod validation (mirrors Pydantic)
│       └── styles/                 # Design system CSS
├── docker/                         # Dockerfiles (api, web, pipeline, seed)
├── docker-compose.yml              # Full stack orchestration
├── .env                            # Local configuration (gitignored)
├── PRD.md                          # Product requirements
├── ARCHITECTURE.md                 # System design
└── README.md                       # Quick start guide
```
