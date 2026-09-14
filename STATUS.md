# PV Maps — Project Status

**Status:** Phase 1 feature-complete, acceptance-blocked
**Last updated:** 2026-09-13
**Backs:** [PRD.md](PRD.md) · [ARCHITECTURE.md](ARCHITECTURE.md)

> The build is done. The evidence is mostly not. Every functional requirement in
> PRD §6 has a working implementation; what is outstanding is the real-world data
> the PRD itself demands before Phase 1 can be called complete. One acceptance
> criterion moved under its own power on 2026-09-13 — the yield model, because
> that one needed compute rather than a person (§11). The two that still block
> are the five real bills and the 50 held-out roofs, and both need a human with
> access to something this repo cannot generate.

---

## 1. Summary

| | |
|---|---|
| Backend tests | **226 passed, 2 failed, 2 skipped** |
| Failing tests | Both deliberate acceptance gates — see §2 |
| Frontend routes | `/` and `/results/:runId` — no others |
| Pilot roofs seeded | 5 |
| Pilot roofs analysed | **5** — pvlib has been run; `yield_source` is `BUILDING` (§11) |
| Phase 2 leakage | None. Grep of `web/src` returns comments only |
| External network deps | **One, and it is live.** `RoofMap` fetches Esri World Imagery tiles from `server.arcgisonline.com` by default — 16 tile requests observed in-browser 2026-09-13. No webfonts, no CDN otherwise. See §4 item 3 |
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
| Roof segmentation IoU ≥ 0.75 on 50 held-out roofs | **STILL NOT RUN**, but no longer for three reasons | Two of the three gaps in §6 item 4 are closed: imagery now has a source (`pipeline/imagery.py`) and `pipeline segment` produces a predicted GeoJSON on the GPU (§12). What remains is the one that always needed a person — **50 hand-drawn ground truths**. The pilot footprints cannot stand in: `seed._square()` generates them as squares round a centroid, so scoring against them would measure nothing |
| Yield model within a defensible published TN range | **PASS** | pvlib run over all five pilot roofs 2026-09-13: **1474.8 – 1675.5 kWh/kWp/yr**, which overlaps the published 1500–1600 band. `roof_analyses` is now populated by `seed`, so runs report `yield_source: BUILDING`. Caveat in §11: the irradiance source is `CLEARSKY_SCALED`, not TMY |
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
| `pipeline/` | Roof geometry, ingest, seed, `yield_physics`, `iou`, **`imagery`**. **pvlib has been run over the pilot roofs** (§11); its output is committed at `pipeline/analyses/pilot_roof_analyses.json` and loaded by `seed`. **Segmentation is now reachable**: `pipeline segment` runs SAM2 on the GPU (§12) |
| `db/` | PostGIS models + Alembic migrations |
| `phase2/` | Allocator + TNERC regulation pack. Quarantined groundwork, imported by nothing in `api/` |

### Frontend — `web/src/`

Two routes, nineteen components, one design system ("Grid Spatial Studio").

| Screen | Components |
|---|---|
| Intake (`/`) | `AddressSearch`, `RoofMap`, `RoofAnalysisPanel`, `ObstructionLedger`, `RoofCorrection`, `BillInputForm`, `DaytimeUseForm` |
| Results (`/results/:runId`) | `CapacityTriCard`, `EnergySplitBar`, `SizingScrubber`, `SizingCurve`, `CandidateTable`, `EconomicsBreakdown`, `AssumptionsPanel`, `RegulatoryBar` |
| Shared | `Workstation`, `Panel`, `Chip`, `Metric`, `format` |

Zod schemas are **not** in field-for-field parity with the Pydantic response
models, and the claim that they were — "verified programmatically" — was wrong.
`usable_area_source` is a three-way `Literal` server-side and was a two-way
`z.enum` in the browser until 2026-09-14; `USER_TRACED` was missing. It went
unnoticed because no UI path reached the `traced_roof` branch, and it surfaced
the instant live measurement did: a 200 with a complete recommendation, thrown
away at the schema boundary as "could not calculate" (§13).

The parity is restored for that field. What does not exist is the programmatic
check the sentence claimed — and a real one, run in CI against the OpenAPI
schema, is worth more than the claim was.

### Functional requirements

| FR | State |
|---|---|
| FR-1 Roof extraction | Precomputed roofs, obstruction geometry, usable area, confidence, numeric correction. **FR-1.1 SAM2 segmentation now runs on the GPU** (§12), though proposals are ranked by a geometric heuristic rather than the classifier FR-1.1 describes. Polygon vertex editing is still a TODO |
| FR-2 Yield physics | pvlib module built **and run**; all five pilot roofs carry their own analysis. Still a scaled clear-sky year rather than TMY |
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

   **It needs a `.env`, because a default port is already taken.** A committed
   `.env` is not possible (gitignored, and it holds the database password), so
   this is the checklist. Ports **re-measured 2026-09-13**; the earlier version of
   this table was written on a different machine and one row of it was wrong here:

   | Var | Default | Set to | Why |
   |---|---|---|---|
   | `WEB_PORT` | 8080 | `8081` | Held by the Oracle TNS listener (`TNSLSNR`). Confirmed still true. |
   | `POSTGRES_PORT` | 5432 | *leave default* | **Correction:** this table previously said a native PostgreSQL 18 occupies 5432. There is no PostgreSQL installed on this machine and 5432 is free. Re-measure before assuming either way — only the host mapping would move; in-network the API always uses `postgis:5432`. |

   Set `CORS_ALLOW_ORIGINS` to match whatever `WEB_PORT` becomes, or the served
   build is blocked by its own API (`api/settings.py` refuses `*` outright).

   A `.env` matching the above is now written, and two `.dockerignore` files were
   added alongside it — see item 7.

3. **Basemap is NOT a flat fill any more, and this entry said it was.**
   Corrected 2026-09-13 after observing it in the browser. `RoofMap` now defaults
   `VITE_BASEMAP_URL` to
   `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/...` and
   attributes "Imagery © Esri, Maxar, Earthstar Geographics" on screen. The
   component's own docstring documents the change deliberately — "It is now a
   switch rather than an absence" — and gives the reason: FR-1.1 needs z19–20 or
   a 10 m terrace is nine pixels across.

   The reason is sound. The consequence is that **ARCHITECTURE.md §9.3 is
   currently violated on the default path**, and on a stage with no wifi the roof
   imagery disappears while the offline fallback happily reports everything else
   as fine — the one failure mode §9.3 exists to prevent.

   Three ways out, cheapest first:

   | Option | Cost | Honours §9.3 |
   |---|---|---|
   | Ship `VITE_BASEMAP_URL=""` in the demo build | one line | yes, back to a flat fill |
   | Pre-seed the browser tile cache for the five pilot roofs | small | partly — first load still needs network |
   | Serve the pilot tiles from our own origin | a day, plus a licence check | yes, and keeps the imagery |

   Whoever runs the demo must pick one. There is no default that is both
   stage-safe and shows imagery.

4. **Fonts are not vendored.** Geist / Inter / JetBrains Mono lead each stack and
   fall back to Segoe UI Variable Display, Segoe UI Variable Text and Cascadia
   Mono — all local to Windows 11, so typography is deterministic on the demo
   machine with zero network. Drop woff2 files into `web/public/fonts` plus a
   `@font-face` block and the stacks pick them up with no other change.

5. **Stale PRD section references remain in `backend/tests/`.** `src/` was swept;
   test files still cite the superseded numbering in failure messages. Cosmetic.

6. **`₹NaN` renders in the value-curve tooltip.** Found in-browser 2026-09-13 on
   the `bldg-demo-1` results screen. Hover any point on the candidate sizing
   curve and the tooltip reads:

   ```
   1.5 kWp
   band        : ₹NaN
   Conservative: ₹19,577
   Optimistic  : ₹27,293
   ```

   `SizingCurve.jsx:42` builds `band: [lo, hi]` as a two-element array to feed
   the shaded `<Area>`. Recharts' `<Tooltip>` renders every series it finds,
   including that one, and the currency formatter turns an array into `NaN`. The
   two real lines beside it are correct, so nothing is miscalculated — but `NaN`
   next to a rupee sign on the one chart a judge is most likely to hover is a bad
   place to have it.

   Fix is one of: `tooltipType="none"` on the `<Area>`, or a `<Tooltip>` filter
   that drops the `band` key. Not applied here — it was found while running the
   stack, not while working on the chart.

7. ~~**No `.dockerignore` anywhere.**~~ **RESOLVED 2026-09-13.** There was none,
   and it had never bitten because nobody had installed dependencies on the host.
   Doing so breaks the web image:

   `docker/web.Dockerfile` runs `npm ci` and **then** `COPY . .`, so a host
   `node_modules` is copied straight over the install the container just did.
   esbuild and rollup ship per-platform binaries, so a Windows install lands in
   an alpine image and `npm run build` fails claiming the wrong binary — with
   nothing on screen pointing at the copy as the cause.

   `web/.dockerignore` and `backend/.dockerignore` now exclude `node_modules` and
   `.venv` respectively. The backend one is only about upload size — no Dockerfile
   there copies `.venv` — but that context is close to a gigabyte once the
   pipeline group is installed, which makes a working build look like a hung one.

8. **Some `PILOT_ROOFS` coordinates are not real places.** Found 2026-09-14 by
   rendering the imagery under each surveyed centroid while testing the GPU path
   (§12).

   `seed.py` was already explicit that `_square()` fabricates the *footprints*.
   What was not known is that at least one **centroid** is fabricated too:
   `bldg-demo-5`, "7 Sathuvachari 5th Cross", sits at 12.9440, 79.1515 — in the
   **Palar riverbed**, with no building within about 100 m. `bldg-demo-4` sits on
   open scrub at the edge of a built-up patch. `bldg-demo-3` (VIT) is genuinely
   correct, and demo-1 and demo-2 are at least on dense rooftops.

   This is harmless for everything Phase 1 currently demonstrates — the tariff
   engine, the optimiser and the economics never look at imagery, and the areas
   are hand-entered constants rather than derived from these points. It is fatal
   for anything that does:

   - Segmentation and IoU on the pilot set measure nothing (§12).
   - The browser map draws a synthetic square over a river for demo-5, on top of
     live Esri imagery (§4 item 3), so a judge who zooms in sees it.

   Replacing them needs five real Vellore addresses with surveyed coordinates —
   the same trip that collects the five TNPDCL bills in §6 item 1.

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

3. ~~**Run pvlib over the pilot roofs.**~~ **DONE 2026-09-13** — see §11. It needs
   no external data, so it moved out of this list; what it does still want is a
   **TMY file for Vellore**, which is the one input that would replace the scaled
   clear-sky year and raise the recorded confidence from 0.55.

4. **Assemble 50 held-out roofs with hand-drawn ground truth**, run
   `pipeline.iou.evaluate()`, and report the actual number — PRD §12 says report
   it honestly whatever it is.

   This is three tasks wearing one number, and only the middle one is the "needs
   a person" part everybody assumes:

   | Missing | Who or what closes it | State |
   |---|---|---|
   | Held-out imagery | `pipeline/imagery.py` fetches and caches the same Esri tiles the browser map draws | **CLOSED 2026-09-14** |
   | **A predicted GeoJSON to score** | `pipeline segment` — imagery → SAM2 on the GPU → polygons → GeoJSON | **CLOSED 2026-09-14** (§12) |
   | 50 hand-drawn ground truths | A person, with the imagery in front of them | **Still open. Nothing here substitutes for it** |

   On the ranking decision this entry used to flag: `segment` picks **the smallest
   mask containing the roof centroid, above `--min-area-m2`**. That is a
   geometric heuristic, it is labelled as one in the CLI output and in every
   feature's `selection` property, and it is *not* the roof/not-roof classifier
   FR-1.1 asks for. It is good enough to put candidate outlines in front of a
   person to correct — the workflow PRD §12 already prescribes — and it is not
   good enough to report an IoU against.

   **Do not be tempted to score against the pilot roofs.** `seed._square()`
   builds those footprints as literal squares round each centroid; the module
   says so ("the outline only has to be in the right place and the right rough
   size"). An IoU against them would measure how square SAM2's output is, and
   PRD §10 asks for something else entirely.

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

### Re-running the physics

`roof_analyses` is populated by `seed` from a committed file, so the ordinary
`docker compose up` path needs no GPU image. Regenerate that file only when the
physics or the pilot roofs change:

```bash
cd backend && python -m pvmaps.pipeline.cli yield --pilot --dry-run --out src/pvmaps/pipeline/analyses/pilot_roof_analyses.json
```

Then regenerate the offline bundle, which reads the same file:

```bash
cd backend && python scripts/build_demo_fallback.py
```

`--pilot` takes the centroids from `PILOT_ROOFS` rather than the database, so
this runs on a machine that has pvlib but no PostGIS. Against a live database,
`pipeline yield` without `--pilot` still writes the rows directly.

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

### Still regional, not per-roof — since closed

`yield_source` was `REGIONAL_FALLBACK` on every run in this sweep: `roof_analyses`
was unpopulated, so the figures above use the Vellore regional band. §11 closes
that. The recommended sizes did **not** move when it did — see §11.

---

## 11. pvlib run over the pilot roofs — 2026-09-13

§6 item 3, done. Run with `pipeline yield --pilot` against
`pvmaps.pipeline.seed.PILOT_ROOFS`, each roof sited at its own centroid.

| Roof | Conservative – expected | Tilt | POA | In published band? |
|---|---|---|---|---|
| `bldg-demo-1` | 1474.8 – 1671.1 kWh/kWp/yr | 15° | 2053.9 kWh/m² | yes |
| `bldg-demo-2` | 1474.8 – 1671.1 | 15° | 2053.9 | yes |
| `bldg-demo-3` | 1474.8 – 1671.0 | 15° | 2053.8 | yes |
| `bldg-demo-4` | 1478.8 – 1675.5 | 15° | 2059.8 | yes |
| `bldg-demo-5` | 1474.8 – 1671.1 | 15° | 2053.9 | yes |

Published band for inland Tamil Nadu is 1500–1600 kWh/kWp/yr. Every roof
overlaps it, so PRD §10's yield criterion is met and `agrees_with_published_band`
returns True without anything having been widened to make it.

The tilt scan picks 15° at every site, which is a few degrees steeper than the
12.9° latitude — the behaviour `best_tilt`'s docstring predicts, arrived at by
evaluating candidates rather than by the rule of thumb.

### Where the rows live, and why not in the database

The output is committed at
`backend/src/pvmaps/pipeline/analyses/pilot_roof_analyses.json` and loaded by
`seed_pilot`, so `docker compose up` gives per-roof yields with no GPU image in
the picture. This is the argument `docker/seed.Dockerfile` already makes about
the seeder's own image, applied one step further: writing five rows should not
require a multi-gigabyte CUDA pull. The physics is still the pipeline's — the
file is generated by `pipeline yield --pilot --out` and never hand-written, and
`tests/test_pilot_analyses.py` fails if it stops covering a pilot roof or drifts
outside the published band.

`scripts/build_demo_fallback.py` reads the same file, so the offline bundle and
the seeded database cannot describe a roof's yield differently. Roofs brought in
by `roofs-import` are filtered out and stay unanalysed, which is what that
command already tells the operator.

**Not yet exercised against a real PostGIS.** This work was done on a second
machine with a GPU but no Docker, no WSL and no PostgreSQL, so the new write in
`seed_pilot` is covered by a fake-connection test and by the offline bundle —
which goes through the same `choose_yield` the API does — and not by an actual
`docker compose up`. The first thing to do on the Docker machine is run it and
confirm `/v1/buildings/bldg-demo-1` reports `yield_source: BUILDING`. Everything
the browser reaches offline already does.

### Three things this does not claim

**It barely differentiates the roofs.** The five bands agree to within 0.3%,
because the pilot roofs are within a few kilometres of each other and every one
of them is run at the same default tilt, the same due-south azimuth and
`shading_retained=1.0`. Per-roof pitch and azimuth are not known — the pilot
footprints are synthetic squares — and per-roof shading is deliberately not
applied here, because `usable_roof` already takes obstructions out of the *area*
and charging the same shadow twice is the failure mode `yield_physics` warns
about. So `yield_source: BUILDING` currently means "pvlib was run at this roof's
coordinates", not "this roof's geometry was measured".

**It is a scaled clear-sky year, not weather.** `irradiance_source` is
`CLEARSKY_SCALED` on every row and the recorded confidence is 0.55 accordingly. A
TMY file for Vellore is the single change that would improve this, and it would
also fix the monthly shape, which currently spreads only 127–152 kWh/kWp and
cannot produce a monsoon dip.

**It changed no headline number.** The regenerated offline bundle returns the
same verdict, the same binding constraint and the same recommended size for all
four rehearsed scenarios as §9's table: demo-1 `RECOMMENDED` 1.5 kWp
sanctioned-bound, demo-2 `NOT_ECONOMIC`, demo-4 `RECOMMENDED` 2.5 kWp roof-bound,
demo-5 `MARGINAL` 0.5 kWp. The pvlib band (1474.8–1671.1) is wider than the
published one (1500–1600) and centred within a rupee's worth of the same place,
so the sizing sweep lands identically. That is a reassuring result rather than a
disappointing one — but it does mean nobody should present this as having
sharpened the recommendation. What it sharpened is the *provenance*.

---

## 12. The GPU plane — implemented 2026-09-14

Until now this project had a GPU story and no GPU path. `roofs.propose_masks`
(SAM2) and `roofs.mask_to_polygons` existed, were documented, were imported by
nothing, and could not have been run: `docker/pipeline.Dockerfile` did not build,
there was no imagery to feed them, and no command joined them together.

All of that is now closed except the checkpoint download and the ground truth.

### What was added

| Piece | Where | Why it did not exist before |
|---|---|---|
| Tile fetch + mosaic | `pipeline/imagery.py` | `data/` is gitignored, so a fresh clone had no pixels. Pulls the **same** Esri tiles `RoofMap` draws, so the model and the household look at one image |
| `pipeline segment` | `pipeline/cli.py` | The missing caller. imagery → SAM2 (GPU) → `mask_to_polygons` → 4326 GeoJSON |
| `pipeline fetch-checkpoint` | `pipeline/cli.py` | Weights are ~180 MB and `.gitignore` excludes `*.pt`, so they cannot be baked into the image |
| `build_mask_generator` | `pipeline/roofs.py` | `propose_masks` reloaded the model per call. One load per **run** now, not per roof |
| 9 tests | `tests/test_segmentation_geometry.py` | `mask_to_polygons` had **zero** tests, despite its docstring saying it is "where the off-by-one errors actually live" |

### Three bugs the Dockerfile was carrying

It had never been built, so none of these had ever surfaced:

1. **`apt-get install python3.12` on Ubuntu 22.04.** Jammy ships python3.10 and
   has no python3.12 package at all. The build could not have got past line 6.
   Python now comes from uv's managed CPython, which is one fewer thing to keep
   in step with the base image.
2. **`cudnn-runtime` base, for nothing.** Torch's Linux wheels vendor their own
   CUDA and cuDNN — this build downloads `nvidia-cudnn-cu13` from PyPI, proving
   it. The base is now `12.4.1-base` (348 MB against ~2.9 GB), which also dodges
   a 670 MB layer that failed to transfer three times on a domestic connection.
3. **`UV_HTTP_TIMEOUT` unset.** The default is 30 s; torch is a 529 MB wheel. The
   first build died on a timeout whose error message blamed the network.

Also `uv pip install sam2` now passes `--no-deps`: SAM2's metadata re-pins torch
and would otherwise re-resolve and re-download the environment built above.

### Mask selection is a heuristic, and is labelled as one

FR-1.1 wants a roof/not-roof classifier to rank SAM2's proposals. There isn't
one. `segment` takes the **smallest mask containing the roof centroid** above
`--min-area-m2`. Every emitted feature carries
`"selection": "smallest-containing-centroid (NOT a classifier)"`, and the command
prints a warning saying the output is proposals for a person to correct.

**This is not an IoU result and must not be reported as one.** See §6 item 4:
the pilot footprints are synthetic squares, so they cannot serve as ground truth
either.

### Verified

- **GPU reaches a container.** `docker run --gpus all nvidia/cuda:12.4.1-base`
  → `nvidia-smi` reports the RTX 4050, 6141 MiB. The `nvidia` container runtime
  is registered with the daemon.
- **Weights fetched.** `checkpoints/sam2.1_hiera_small.pt`, 184 MB, valid torch
  archive, from Meta's published CDN.
- **`docker compose --profile pipeline config`** resolves with the GPU
  reservation and both binds (`./data`, `./checkpoints`).
- **236 tests pass** (was 227), mypy strict and ruff clean on every changed
  module.
- `yield --pilot` still produces byte-identical output after the `_roof_targets`
  refactor it now shares with `segment`.

### It ran. Here is what came back.

`segment --pilot` on the RTX 4050, SAM2.1 hiera-small, z19, 3x3 tile mosaic.
Point-prompted at each roof's surveyed centroid; all three returned scales kept,
areas measured in UTM 44N:

| Roof | Hand-measured | SAM2 scales offered | Best score |
|---|---|---|---|
| `bldg-demo-1` | 118 m² | 47, 39, 31 444 m² | 0.928 |
| `bldg-demo-2` | 96 m² | 38, 723, 7 169 m² | 0.338 |
| `bldg-demo-3` | 1 940 m² | 235, 324, 4 167 m² | 0.814 |
| `bldg-demo-4` | 62 m² | 995, 1 608, 367 m² | 0.751 |
| `bldg-demo-5` | 104 m² | 8 775, 33 616, 2 085 m² | 0.670 |

**Not one roof has a scale within a factor of three of its hand-measured area.**
That is the honest result and it should not be smoothed over.

### Why — and it is not the segmentation

Rendering the imagery under each centroid settles it
(`data/pilot-contact-sheet.png`, regenerate with the snippet in git history):

| Roof | What is actually at the surveyed coordinate |
|---|---|
| `bldg-demo-1` | Dense urban rooftops. Plausible |
| `bldg-demo-2` | Dense urban rooftops. Plausible |
| `bldg-demo-3` | A large institutional building on the VIT campus. **Genuinely right** |
| `bldg-demo-4` | Open scrub at the edge of a built-up patch. Marginal |
| `bldg-demo-5` | **The Palar riverbed. There is no building within ~100 m** |

For demo-5, SAM2 returned a riverbank, a terrain block and a sandbar. All three
are correct segmentations of real objects. None is a roof, because there is no
roof. The model did its job; the coordinate is fiction.

So `PILOT_ROOFS` is synthetic further down than §6 item 4 assumed. It was already
known that `_square()` fabricates the footprints. It now turns out **some of the
centroids are invented too** — see §4 item 8. Every imagery-based number for the
pilot set is therefore meaningless until real addresses replace them, and that
includes any future IoU.

### Consequences for the output format

`segment` emits **every** scale rather than a single winner, because picking by
SAM2's confidence score lands between 0.1x and 84x of the hand-measured area.
The score measures how cleanly a region was segmented, not whether it is a roof.
Each feature carries `"selection": "...UNRANKED BY ROOFNESS -- pick by hand (no
classifier)"`. This is a proposal generator feeding the hand-correction workflow
PRD §12 prescribes, and nothing more.

### Gotcha for anyone re-running this from Git Bash

MSYS rewrites a leading `/data/...` argument into a Windows path, so the GeoJSON
lands *inside the container* at `C:/Program Files/Git/data/...` and the host
mount stays empty, with a success message either way:

    MSYS_NO_PATHCONV=1 docker compose --profile pipeline run --rm pipeline         segment --pilot --out //data/predicted-pilot.geojson

---

## 13. Live roof measurement — any address, 2026-09-14

**This reverses PRD §9 and ARCHITECTURE.md §9.3, on purpose.** Those rules bought
a stage-proof demo — precomputed roofs, zero network — at the price of a product
that could only answer for five seeded addresses. It now answers for any address
in India, and the cost is that a demo depends on a reachable geocoder, a
reachable tile server and a working GPU.

### What was built

| Piece | Where |
|---|---|
| `GET /v1/geocode` | Nominatim proxy, `countrycodes=in` so a US suburb cannot appear with an INR tariff |
| `POST /v1/roof-at` | Proxies to the segmenter; distinguishes "no imagery" from "service starting" |
| `pvmaps.segmenter` | FastAPI + SAM2 on the GPU, model loaded once at startup |
| `segmenter` compose service | Same 6.8 GB image as `pipeline`, different entrypoint, **not** behind the pipeline profile |
| `LocationSearch` | Pilot roofs and geocoder hits in one list, pilot first |
| Always-on map | Centred on Vellore before you type; flies to each address |

The API still does **not** import torch — it makes an HTTP call.
`test_architecture.py` enforces that, and the API image stays at 303 MB.

### Why SAM2, and not UNet or a footprint dataset

Measured at the same dense-Vellore point, 2026-09-14:

| Source | Buildings within 120 m | Verdict |
|---|---|---|
| OpenStreetMap | 2 | Far too sparse |
| Microsoft GlobalMLBuildingFootprints | 12; nearest 3 472 m² and 7 761 m² | Merges whole blocks |
| SAM2 on z19 imagery | Outlines individual roofs | **Best available** |

ML footprint datasets systematically under-segment dense informal settlements —
precisely the housing this product exists for. Replacing SAM2 would lower
accuracy, not raise it.

### The ranking signal is area, NOT SAM2's confidence

On the VIT tile SAM2 scored the outline of the *entire complex* at **0.069** and
a kiosk in its courtyard at **0.814**. Its confidence measures how cleanly a
region was segmented, not whether the region is a roof, and it is close to
inverted for this purpose. So `segmenter/service.py:_rank` orders by
plausible-area-first (15–5 000 m²), largest within the window, and every scale is
returned for the user to overrule (FR-1.5).

Observed live on `Gandhi Road, Kosapet, Vellore`: candidates of 84 m², 28 m² and
44 438 m². The window rejected the 44 438 m² blob and picked 84 m² — a real
rooftop. Score-based ranking would not reliably have.

### Two bugs this surfaced, neither introduced by it

1. **Zod/Pydantic drift.** `usable_area_source` is a three-way `Literal` in
   `api/schemas.py` but a two-way `z.enum` in the browser — `USER_TRACED` was
   missing. Nothing had ever reached the `traced_roof` branch from the UI, so the
   API answered 200 with a complete recommendation and the browser discarded it
   at the schema boundary, reporting "could not calculate". §3's claim that the
   schemas are in field-for-field parity was **false**, and a parity check that
   runs in CI would be worth more than the claim.
2. **`building_id` could not be omitted.** The API documents "exactly one of
   `building_id` and `traced_roof`" and enforces `min_length=1`, so an empty
   string is a 422. The browser has to omit the key entirely.

### Honest limits

- A measured roof is a **footprint**. Obstructions and the parapet setback have
  NOT been deducted, so it is less conservative than a hand-checked pilot roof.
  The results screen labels it "Measured live" and the assumptions panel says so.
- `yield_source` is `REGIONAL_FALLBACK` for every measured roof — pvlib has only
  been run over the five pilot centroids.
- Still no roof/not-roof classifier (FR-1.1). The area window is a heuristic
  standing in for one.
- Cold measurement ≈ 6–7 s (nine tile fetches, then SAM2); warm ≈ 0.5–1.6 s.
