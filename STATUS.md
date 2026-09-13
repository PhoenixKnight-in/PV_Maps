# PV Maps — Project Status

**Status:** Phase 1 feature-complete, acceptance-blocked
**Last updated:** 2026-09-13
**Backs:** [PRD.md](PRD.md) · [ARCHITECTURE.md](ARCHITECTURE.md)

> The build is done. The evidence is not. Every functional requirement in PRD
> §6 has a working implementation; what is outstanding is the real-world data
> the PRD itself demands before Phase 1 can be called complete.

---

## 1. Summary

| | |
|---|---|
| Backend tests | **224 passed, 2 failed, 1 skipped** |
| Failing tests | Both deliberate acceptance gates — see §2 |
| Frontend routes | `/` and `/results/:runId` — no others |
| Pilot roofs seeded | 5 |
| Phase 2 leakage | None. Grep of `web/src` returns comments only |
| External network deps | None. No webfonts, no CDN, no tile service |
| Stack | `docker compose up` verified end to end — see §4 item 2 for the required `.env` ports |
| Frontend ↔ backend | **Connected and verified live** — see §10 |

The two red tests are **not** defects. `tests/test_tariff_golden.py` says so in its
own docstring: *"THIS TEST IS EXPECTED TO FAIL ON A FRESH CLONE. That is the
point."* They stay red until someone feeds them reality.

---

## 2. PRD §10 acceptance criteria — scorecard

| Criterion | Status | What is missing |
|---|---|---|
| Tariff engine reproduces 5 real TNPDCL bills to the rupee | **BLOCKED** | `backend/tests/fixtures/bills/real_bills.json` holds five `TODO-*` placeholders with `units_kwh: null`. Zero real bills collected |
| Roof segmentation IoU ≥ 0.75 on 50 held-out roofs | **NOT RUN** | `pipeline/iou.py` harness exists and is tested. There is **no held-out dataset** — `tests/fixtures/` contains only `bills/` |
| Yield model within a defensible published TN range | **FALLBACK ONLY** | `roof_analyses` is never populated for the pilot roofs, so every sizing run reports `yield_source: REGIONAL_FALLBACK`. pvlib has not been run against a real roof |
| Sizing engine never exceeds roof or sanctioned-load max | **PASS** | Enforced in `sizing/optimise.py`, covered by `test_sizing.py` and `test_capacity.py` |
| Economics keep self-consumed and exported separate | **PASS** | Structural: `CandidateOut` carries them as separate `RangeOut` fields; the UI renders them as separate line items (FR-4.2, FR-4.3) |
| Five pilot addresses return roof results under two seconds | **PASS** | `test_latency.py` asserts a roof budget and a sizing budget across all five |
| Every Phase 1 result carries the disclaimer | **PASS** | Rendered from `recommendation.grid_disclosure` with the exact PRD string as fallback; verified in-browser on every path including `NO_CAPACITY` |

---

## 3. What is built

### Backend — `backend/src/pvmaps/`

| Module | State |
|---|---|
| `tariff/` | Decimal telescopic engine, dated versioned rule packs. Complete, **unvalidated** |
| `sizing/` | Capacity conversion, self-consumption model, candidate optimiser, subsidy. Complete and tested |
| `api/` | `GET /v1/search`, `GET /v1/buildings/{id}`, `POST /v1/sizing-runs`, `POST /v1/bill-extract`, `GET /v1/tariffs/current`, `GET /healthz`. No transformer, quota, allocation or grid-eligibility endpoint (ARCHITECTURE.md §5.2) |
| `pipeline/` | Roof geometry, ingest, seed, `yield_physics`, `iou`. Built; **pvlib not yet run on pilot roofs** |
| `db/` | PostGIS models + Alembic migrations |
| `phase2/` | Allocator + TNERC regulation pack. Quarantined groundwork, imported by nothing in `api/` |

### Frontend — `web/src/`

Two routes, nineteen components, one design system ("Grid Spatial Studio").

| Screen | Components |
|---|---|
| Intake (`/`) | `AddressSearch`, `RoofMap`, `RoofAnalysisPanel`, `ObstructionLedger`, `RoofCorrection`, `BillInputForm`, `DaytimeUseForm` |
| Results (`/results/:runId`) | `CapacityTriCard`, `EnergySplitBar`, `SizingScrubber`, `SizingCurve`, `CandidateTable`, `EconomicsBreakdown`, `AssumptionsPanel`, `RegulatoryBar` |
| Shared | `Workstation`, `Panel`, `Chip`, `Metric`, `format` |

Zod schemas are in field-for-field parity with the Pydantic response models —
verified programmatically. A field the API emits can no longer be silently
dropped by browser-side parsing.

### Functional requirements

| FR | State |
|---|---|
| FR-1 Roof extraction | Precomputed roofs, obstruction geometry, usable area, confidence, numeric correction. Polygon vertex editing is still a TODO |
| FR-2 Yield physics | pvlib module built; pilot roofs currently use the regional band |
| FR-3 Bill and tariff intake | Manual entry always available; optional upload + extraction; three daytime questions |
| FR-4 Bill-to-Roof Optimiser | Full candidate sweep, self-use/export split, separate rupee line items, value curve, scrubber |
| FR-5 Interface | Complete |
| FR-6 Synthetic Grid Pressure | **Not built** — correctly, it is optional and post-acceptance |
| FR-7 Grid Passport | **Phase 2** — out of scope |

---

## 4. Known code gaps

1. ~~**Demo fallback is dead code.**~~ **RESOLVED 2026-09-13.** `web/src/api/dataSource.ts`
   now wraps every screen-facing call in `withFallback()`, and `probeApi()` runs
   on mount from `App.jsx`. Verified in-browser with the API down: the offline
   strip renders, address search resolves against the bundled pilot table, and a
   sizing run returns the stored result for that roof labelled by
   `OfflineResultNotice`. Outage detection is deliberately narrow — 502/503/504
   and timeouts fall back; a 500 is our bug and still surfaces.

2. ~~**`docker compose up` unverified.**~~ **RESOLVED 2026-09-13.** Exercised end
   to end from a clean volume: `postgis` healthy → `migrate` exited 0 → `seed`
   exited 0 → `api` healthy → `web` serving. `/healthz` reports
   `{"status":"ok","database":"ok"}`.

   **It needs a `.env` on this machine, because two default ports are already
   taken** — and both failures are silent-ish rather than obvious:

   | Var | Default | Must be | Why |
   |---|---|---|---|
   | `POSTGRES_PORT` | 5432 | e.g. `55432` | A native PostgreSQL 18 runs here with unrelated databases. Only the host mapping moves; in-network the API still uses `postgis:5432`. |
   | `WEB_PORT` | 8080 | e.g. `8081` | Held by the Oracle TNS listener (`TNSLSNR`). |

   Set `CORS_ALLOW_ORIGINS` to match whatever `WEB_PORT` becomes, or the served
   build is blocked by its own API (`api/settings.py` refuses `*` outright).

3. **Basemap is a flat fill.** `RoofMap` carries a `TODO` to point at a pilot
   raster served from our own origin. A public tile style would be exactly the
   network dependency ARCHITECTURE.md §9.3 forbids.

4. **Fonts are not vendored.** Geist / Inter / JetBrains Mono lead each stack and
   fall back to Segoe UI Variable Display, Segoe UI Variable Text and Cascadia
   Mono — all local to Windows 11, so typography is deterministic on the demo
   machine with zero network. Drop woff2 files into `web/public/fonts` plus a
   `@font-face` block and the stacks pick them up with no other change.

5. **Stale PRD section references remain in `backend/tests/`.** `src/` was swept;
   test files still cite the superseded numbering in failure messages. Cosmetic.

---

## 5. Open questions from PRD §10 "must verify"

These are unresolved by design. The code refuses to guess rather than papering
over them.

| Question | Where it bites |
|---|---|
| **Bimonthly billing-cycle treatment** | TN bills are bimonthly; the free allowance reportedly rises to 200 units for consumers at or below 500 units bimonthly, which is *not* a 2× scaling. `tariff/schedule.to_billing_period()` raises `NotImplementedError` rather than guess |
| **Solar export settlement rate** | Currently modelled as **₹0/kWh** and labelled unverified on screen. This materially suppresses recommended sizes — it is the single assumption most likely to change the headline number |
| **Self-consumption ranges per household profile** | Drives the widest band in the whole calculation |
| **VIT tariff and sanctioned demand** | PRD §11 says show physical MWp only until these exist. Currently honoured |
| **Network charges and subsidy rule confirmation** | Subsidy pack is dated but unverified against primary source |

---

## 6. How to proceed

Order matters: items 1 and 2 can change every number downstream.

### Blocked on real-world data — needs a person

1. **Collect five real TNPDCL domestic bills.** Different consumption levels —
   at least one inside the free slab, one above 400 units. Fill
   `backend/tests/fixtures/bills/real_bills.json` (read its `_README` first for
   the PII rules), then run:

   ```bash
   cd backend && .venv/Scripts/python.exe -m pytest tests/test_tariff_golden.py -q
   ```

   Fix the **schedule** or the **engine** to match the bill. Never the reverse.
   This is the highest value-per-hour task in the project: it is the only
   component a judge can falsify from the audience.

2. **Read the primary TNERC / TNPDCL tariff order.** Closes the bimonthly
   question, lets `verification_status` move to
   `VERIFIED_AGAINST_PRIMARY_SOURCE`, and yields the real export settlement rate
   that replaces the ₹0 placeholder.

3. **Run pvlib over the pilot roofs** so `roof_analyses` is populated and results
   read "this roof" rather than "regional band".

4. **Assemble 50 held-out roofs with hand-drawn ground truth**, run
   `pipeline.iou.evaluate()`, and report the actual number — PRD §12 says report
   it honestly whatever it is.

### Needs no external data — can start immediately

5. ~~**Wire the demo fallback into the UI.**~~ **DONE** — see §4 item 1.
6. ~~**Verify `docker compose up`**~~ **DONE 2026-09-13** — see §4 item 2.
7. ~~**Test the PRD §9 scenarios through the browser.**~~ **DONE 2026-09-13** —
   all five pilot roofs offline, then the full use-profile sweep live. See §9.
8. **Choose and rehearse the fallback demo path**: one pre-validated address plus
   one pre-validated bill scenario. `bldg-demo-1` (12 Katpadi Road) is the
   strongest candidate — it is the only roof where the recommendation sits
   *below* both ceilings, which is the PRD §11 reveal.

### Deliberately not next

- FR-6 Synthetic Grid Pressure — optional, and only after the criteria above pass
- Anything from Phase 2 (DT capacity, queue, allocation, area analytics). The
  Stitch designs for these exist under
  `stitch_pv_maps_spatial_intelligence_platform/` as **visual reference only**

---

## 7. Running it

```bash
docker compose up
```

One command brings up PostGIS, migrations, seed, API and web. The offline
pipeline is a separate profile and is never started during a demo.

For frontend work against a running API:

```bash
npm run dev --prefix web
```

Serves on `http://localhost:5173`; expects the API on `http://localhost:8000`
(`VITE_API_BASE_URL` overrides).

---

## 8. Product boundary — still holding

Phase 1 does not show, and must not show, a DT quota remaining, a queue
position, a grid-approved capacity or an approval prediction (PRD §2.3, §3.2).
An audit of `web/src` returns matches for those terms only inside comments
explaining their deliberate absence. Every result carries, verbatim:

> Grid connection is not verified. Official TNPDCL feasibility is required before installation.

---

## 9. Browser scenario walkthrough — 2026-09-13

All five bundled pilot roofs driven end to end through `npm run dev` with the
API **down**, so this exercises the §9.3 fallback path at the same time. Each row
was asserted programmatically against the rendered DOM, not eyeballed.

| Roof | Scenario | Verdict | Binding | Recommended | Result |
|---|---|---|---|---|---|
| `bldg-demo-1` | Normal household, 420 kWh/mo | `RECOMMENDED` | Sanctioned load | 1.5 of 3.0 kWp | **PASS** |
| `bldg-demo-2` | Free-slab, 90 kWh/mo, nobody home | `NOT_ECONOMIC` | Sanctioned load | — | **PASS** |
| `bldg-demo-3` | VIT Technology Tower | *no recommendation* | — | — | **PASS** |
| `bldg-demo-4` | Daytime-heavy, small roof | `RECOMMENDED` | **Roof** | 2.5 kWp | **PASS** |
| `bldg-demo-5` | Home all day, low units | `MARGINAL` | Sanctioned load | 0.5 kWp | **PASS** |

Asserted on every result screen: the PRD §5.2 disclosure verbatim;
self-consumed and exported rendered as separate figures (FR-4.2) with a
separate export-credit line (FR-4.3); every inferred figure carrying its band
(NFR-2, 6–8 bands per screen); and **zero** matches for queue position, quota
remaining or allocation delta (PRD §2.3, §3.2).

Two paths worth calling out because they are the ones most likely to regress:

- **`bldg-demo-4` is the only roof where the roof, not the connection, binds.**
  It renders "Your roof is the limit." — the opposite copy branch from every
  other pilot roof, and the only coverage that branch has.
- **`bldg-demo-3` (VIT) has no stored recommendation at all.** Submitting a bill
  against it stays on intake and explains that PV Maps publishes a physical
  rooftop potential but no rupee figures. Asserted: **no rupee figure appears
  anywhere on the page**, which is PRD §11 holding.

### Offline caveat — since closed

Offline, `createSizingRun()` returns the **stored** result for the roof and
ignores the submitted profile, correctly: reimplementing the optimiser in the
browser would be a second unverified engine. So the walkthrough above proves
*result-state rendering*, not that the inputs do anything. That gap is now
closed by §10.

---

## 10. Live stack — frontend connected to backend, 2026-09-13

`docker compose up` brings up PostGIS + API; the browser talks to it directly.
Confirmed from inside the page: the offline strip is gone, and one intake run
issues `/healthz`, `/v1/search`, `/v1/buildings/{id}` and `/v1/sizing-runs`, then
lands on a real opaque run id (`/results/HUv1Fs…`) rather than the offline
`/results/preview`.

**The same roof and bill now give a different answer live than the bundle
stored** — 1.0 kWp against the bundle's 1.5 — because the live optimiser reads
the submitted profile. That is the point, and it is what the sweep below shows.

### PRD §9 use profiles, live against `bldg-demo-1` (420 kWh/mo, 3.0 kW sanctioned)

| Occupancy | Recommended | Annual bill savings | Self-consumed share |
|---|---|---|---|
| `EMPTY_WEEKDAYS` | 0.5 kWp | ₹4,990 – ₹7,476 | 63% |
| `PARTIAL` | 1.0 kWp | ₹11,340 – ₹13,860 | 79% |
| `HOME_ALL_DAY` | 1.5 kWp | ₹16,481 – ₹18,900 | 84% |
| `DAYTIME_HEAVY` | 2.0 kWp | ₹21,032 – ₹23,044 | 87% |

Monotonic in the right direction, and the load-addition modifiers behave:
`EV_CHARGED_BY_DAY` recommends 1.0 kWp, `EV_CHARGED_AT_NIGHT` only 0.5 kWp — a
night-charged EV gives solar nothing to displace.

Every one of these sits **below** the 3.0 kWp sanctioned ceiling. The economic
optimum binds before the connection does, which is PRD §11's argument holding
under real inputs rather than stored ones.

### Still regional, not per-roof

`yield_source` remains `REGIONAL_FALLBACK` on every live run: `roof_analyses` is
still unpopulated, so these figures use the Vellore regional band. §6 item 3
(run pvlib over the pilot roofs) is what changes that — the numbers above will
move when it does.
