# PV Maps — Product Requirements Document

**Status:** Draft v1.1  
**Last updated:** 2026-09-10  
**Owner:** Parthiban

> **Every solar calculator tells you what a roof can hold. PV Maps tells you what a bill can use.**

---

## 1. Product summary

PV Maps is a responsive web application for Tamil Nadu rooftop-solar sizing.

It combines roof analysis with a household's actual electricity bill to recommend the solar system size that is financially sensible for that household. It does not recommend the largest system that can physically fit on the roof.

Phase 1 is the **Bill-to-Roof Optimiser**.

Phase 2 is **Grid Passport**, a separate utility-data product that verifies whether the local electricity network can accept the proposed system. Phase 1 must not claim to perform Phase 2.

---

## 2. Problem

### 2.1 Roof potential is not a buying decision

Existing solar tools usually answer:

> This roof can fit 6.4 kWp.

That is physical potential, not a purchase recommendation. The system that makes financial sense is constrained by:

| Constraint | Meaning |
|---|---|
| Usable roof area | Space remaining after visible obstructions and shading |
| Sanctioned load | Solar capacity cannot exceed the service connection's sanctioned load |
| Electricity use | Solar is valuable when it is self-consumed or exported under acceptable settlement terms |
| Tariff and settlement | Import savings and exported-energy credit are not the same value |

A roof may fit 6.4 kWp, while a 2.8 kWp system is the financially rational purchase for the household using that roof.

### 2.2 Average-tariff payback is misleading

Tamil Nadu electricity bills use category-specific and telescopic tariffs. Solar used inside the home offsets imported electricity. Surplus exported to the grid follows the applicable solar settlement mechanism.

Therefore, PV Maps must not calculate:

~~~text
annual solar kWh × one average tariff = savings
~~~

It must model the user's bill, sanctioned load, likely daytime use, candidate system size, import offset, and export value separately.

### 2.3 Grid feasibility is real, but not solvable from imagery alone

A distribution transformer can constrain rooftop solar. However, satellite imagery, OSM transformer pins, road-network Voronoi regions, and estimated building demand cannot prove:

- the exact transformer serving a specific electricity connection;
- transformer nameplate rating, feeder ampacity, or peak load;
- installed grid-connected solar capacity;
- feasibility-approved but uncommissioned projects; or
- the live first-come-first-served application queue.

Phase 1 may estimate **grid pressure** for research, but it must never show a quota remaining, queue position, grid-approved capacity, or approval prediction.

---

## 3. Goals and non-goals

### 3.1 Phase 1 goals — Bill-to-Roof Optimiser

- **G1** — Find usable roof area and estimate solar yield from an entered address.
- **G2** — Read a TNPDCL bill, or accept confirmed manual bill values.
- **G3** — Use sanctioned load, consumption, tariff, and daytime-use assumptions to recommend the financially sensible system size.
- **G4** — Clearly compare physical roof maximum, sanctioned-load maximum, and recommended capacity.
- **G5** — Separate self-consumed solar, exported solar, import savings, export credit, subsidy, and payback.
- **G6** — Provide one fast, memorable demo over a precomputed Vellore pilot area.

### 3.2 Phase 1 non-goals

- Grid approval, transformer quota, queue position, or remaining transformer capacity.
- A synthetic model labelled as an official utility result.
- Capacity allocation between neighbours.
- Peer-to-peer rooftop trading.
- Chatbots, LLM features, generic AI recommendations, accounts, payments, installer marketplace, IoT monitoring, or national coverage.

---

## 4. Users

| User | Job to be done | PV Maps outcome |
|---|---|---|
| Homeowner | How much solar should I actually buy? | A bill-aware recommended system size and transparent payback range |
| Installer / EPC | What system should I propose before preparing a quote? | A roof, sanctioned-load, and demand-aware pre-design |
| Institution / campus manager | How much physical roof potential is there, and what should be studied next? | Physical potential plus bill-backed economic scenarios |

---

## 5. User inputs and outputs

### 5.1 Required user inputs

| Input | Required for | Notes |
|---|---|---|
| Address or dropped map pin | Roof analysis | Required |
| Latest electricity bill upload | Personalised recommendation | Preferred |
| Manual bill entry | Fallback | Tariff category, sanctioned load, billing units, billing dates |
| Daytime occupancy | Self-consumption estimate | One quick choice |
| Major daytime loads | Self-consumption estimate | AC, pump, EV, shop/office, or none |
| Expected load additions | Future-ready sizing | EV, AC, or none |

The user must not be asked to identify their transformer or estimate their own tariff.

### 5.2 Phase 1 outputs

| Output | Meaning |
|---|---|
| Roof maximum kWp | Physical maximum after usable-area and shading assumptions |
| Sanctioned-load maximum kWp | Maximum allowed by the bill's sanctioned load |
| Recommended kWp | Best-value system size under the entered assumptions |
| Annual generation range | Conservative and expected annual kWh |
| Self-consumed and exported kWh | Separate yearly estimates |
| Savings range and payback range | Bill-aware, never fake precision |
| Assumptions | Tariff version, cost, subsidy, use profile, export settlement |

Every result must display:

> **Grid connection is not verified. Official TNPDCL feasibility is required before installation.**

---

## 6. Functional requirements

### FR-1 — Roof extraction

- **FR-1.1** Produce roof-mask proposals from Google or Bhuvan imagery at zoom level 19–20 using SAM2 plus a roof/not-roof classifier.
- **FR-1.2** Detect or allow manual marking of visible obstructions such as water tanks, stairheads, and parapets.
- **FR-1.3** Calculate usable roof area in square metres.
- **FR-1.4** Apply visible shading assumptions where supported by imagery; show a confidence score.
- **FR-1.5** Provide a manual roof-boundary correction control for all demo locations.
- **FR-1.6** Persist footprint, usable area, obstruction geometry, assumptions, and confidence.

Roof segmentation is input infrastructure, not PV Maps' claimed innovation.

### FR-2 — Yield physics

- **FR-2.1** Use pvlib for plane-of-array irradiance, tilt/azimuth selection, temperature derate, and soiling assumptions.
- **FR-2.2** Apply usable-area and shading losses from FR-1.
- **FR-2.3** Produce monthly and annual kWh per kWp, with expected and conservative ranges.
- **FR-2.4** Use documented physical assumptions. Do not substitute an opaque ML yield prediction.

### FR-3 — Bill and tariff intake

- **FR-3.1** Accept a current electricity-bill PDF or image.
- **FR-3.2** Offer manual input when upload or extraction is unavailable.
- **FR-3.3** Extract or request confirmation of tariff category, sanctioned load, phase, billing-cycle units, billing dates, and relevant charges.
- **FR-3.4** Use OCR only to copy visible fields. The user must be able to correct every extracted value before calculation.
- **FR-3.5** Ask three behaviour questions: daytime occupancy, major daytime loads, and likely near-term load additions.
- **FR-3.6** Store tariffs, network charges, subsidies, and export-settlement rules as dated and versioned configuration.

### FR-4 — Bill-to-Roof Optimiser

For each candidate system size between 0.5 kWp and the feasible maximum, calculate generation, likely self-consumption, exported surplus, annual bill effect, upfront cost, subsidy, and payback.

~~~text
feasible maximum = minimum(roof maximum, sanctioned-load maximum)

recommended size = candidate system size with the strongest
private economic value under the selected bill and use assumptions
~~~

- **FR-4.1** Never value all generation at one average tariff.
- **FR-4.2** Show self-consumed kWh and exported kWh as separate numbers.
- **FR-4.3** Show import-cost offset and export credit as separate rupee line items.
- **FR-4.4** Return roof maximum, sanctioned-load maximum, recommended size, annual generation, savings range, cost, subsidy, and payback range.
- **FR-4.5** Render a system-size-versus-value curve and identify the recommendation on it.
- **FR-4.6** Without a bill, use only an explicitly labelled indicative profile and do not show a precise personal payback.

### FR-5 — Interface

The core flow is:

~~~text
Address → roof outline → physical maximum
        → bill upload or manual bill details
        → daytime-use inputs
        → recommended system size
        → savings / export / payback curve
        → official TNPDCL feasibility handoff
~~~

The result screen must make the distinction visually clear:

| Label | Meaning |
|---|---|
| Roof maximum | What physically fits |
| Sanctioned-load maximum | What the service connection permits |
| Recommended system | What the bill can use economically |
| Grid feasibility | Not verified in Phase 1 |

### FR-6 — Synthetic Grid Pressure Model (optional research view only)

If time remains after all Phase 1 acceptance criteria pass, PV Maps may use:

- OSM transformer locations;
- surveyed transformer locations;
- building footprint, floors, and building type; and
- publicly visible rooftop solar patterns

to return only:

~~~text
transformer-location confidence
estimated local load pressure
estimated solar saturation
grid-risk: low / medium / high
~~~

It must display:

> **Estimated from public spatial data. This is not TNPDCL feasibility approval.**

This view must not affect recommended kWp, payback, or any grid-eligibility statement.

### FR-7 — Grid Passport (Phase 2)

Grid Passport is a utility-data and workflow integration, not a synthetic-grid model.

| Required data | Source of truth |
|---|---|
| Consumer service to pole, feeder, and DTR mapping | TNPDCL service and network records |
| DTR rating, feeder, conductor, ampacity, and peak load | TNPDCL asset and operations records |
| Commissioned solar capacity | Net-meter and commissioning register |
| Submitted, approved, withdrawn, and expired applications | TNPDCL rooftop-solar application system |
| Current capacity rule | TNERC/TNPDCL policy pack |

- **FR-7.1** The user enters consumer/service number with region code and authorises lookup by OTP, or submits a current bill.
- **FR-7.2** PV Maps receives a dated source-backed capacity snapshot from an authorised utility or partner workflow.
- **FR-7.3** Return one of: Verified available; Likely available, not reserved; Grid constrained; or Not connected to official data.
- **FR-7.4** PV Maps may call a slot reserved only after successful official TNPDCL application submission and timestamping.
- **FR-7.5** Every Grid Passport result includes source, timestamp, rule version, and freshness status.

---

## 7. Non-functional requirements

- **Privacy:** Electricity bills contain personal data. Encrypt extracted profiles; delete the original bill image after confirmation unless the user explicitly asks to retain it.
- **Honesty:** Display assumptions and ranges. A bill without interval data cannot support an exact self-consumption claim.
- **Traceability:** Every tariff, subsidy, panel-price, and export-settlement rule includes a source and effective date.
- **Separation of states:** Roof-feasible, bill-recommended, and grid-verified are distinct states and must never be conflated.
- **Web delivery:** The product is a responsive browser experience; no native mobile application is in Phase 1.
- **Latency:** Address-to-roof result should return in under two seconds for the precomputed pilot area.
- **Reproducibility:** Store calculation inputs and tariff version with each sizing run.

---

## 8. Architecture

~~~text
INGEST
  Google/Bhuvan imagery
  Irradiance and weather assumptions
  TNPDCL tariff and settlement rules
  Electricity bill or confirmed manual details
          │
          ├── A. Roof extraction
          │      roof mask → obstructions → usable area → confidence
          │
          ├── B. Yield physics
          │      pvlib → monthly / annual generation range
          │
          ├── C. Bill profile
          │      confirmed bill data + daytime-use inputs
          │
          └── D. Bill-to-Roof Optimiser
                 candidate kWp sizes
                 → self-use / export split
                 → tariff settlement
                 → savings and payback ranges
                 → recommended system size
                          │
                          ▼
       Map UI · physical maximum · recommendation · value curve

PHASE 2 ONLY
  TNPDCL-authorised service, DTR, feeder, and application-queue data
  → Grid Passport
~~~

**Stack:** PostGIS, Python with FastAPI, pvlib, rasterio, and SAM2; MapLibre GL for the map interface.

**Core schema:**

~~~sql
buildings(
  id, geom, roof_area_m2, usable_area_m2, typology, confidence
)

roof_analyses(
  id, building_id, yield_kwh_per_kwp, loss_assumptions, analysed_at
)

tariff_schedules(
  id, version, effective_from, category, rules_json
)

bill_profiles(
  id, encrypted_profile, tariff_category, sanctioned_load_kw,
  billing_units, daytime_profile, created_at
)

sizing_runs(
  id, building_id, bill_profile_id, roof_max_kwp,
  recommended_kwp, savings_range_json, payback_range_years,
  assumptions_json
)

-- Phase 2 only
grid_passports(
  id, service_reference_hash, dtr_reference, source, observed_at,
  policy_version, status, available_kw, staleness
)
~~~

---

## 9. Scope and phasing

### Phase 1 — Bill-to-Roof Optimiser, 1–2 weeks

**Pilot:** One Vellore ward plus hand-corrected VIT demo roofs. Precompute all roof data. Do not run segmentation live on stage.

#### Week 1 — working calculation spine

1. Prepare satellite tiles and manually correct demo roofs.
2. Build and validate pvlib yield calculations.
3. Build the TNPDCL tariff and settlement engine before building the interface.
4. Create manual bill-profile entry and the three daytime-use inputs.
5. Build the candidate-size optimiser, self-consumption/export split, savings range, and payback curve.

#### Week 2 — evidence and demo quality

6. Add bill upload, field extraction, and user correction.
7. Build the address-to-result map flow and roof correction.
8. Measure roof segmentation IoU on 50 held-out roofs.
9. Test low-daytime-use, normal-household, and high-daytime-use or EV-ready scenarios.
10. Prepare a pre-validated fallback address and bill scenario for the demo.

### Phase 2 — Grid Passport

Begin only after obtaining at least one of:

- authorised TNPDCL data access;
- a partner workflow that returns dated official feasibility reports; or
- a pilot agreement exposing service-to-DTR and rooftop-application data.

Walking surveys, OSM pins, and satellite data alone are not sufficient for Grid Passport.

---

## 10. Acceptance criteria

| Component | Acceptance criterion |
|---|---|
| Roof segmentation | IoU of at least 0.75 on 50 held-out roofs; report the actual number |
| Yield model | Within a defensible published Tamil Nadu yield range, or assumptions are reviewed |
| Baseline tariff engine | Reproduces five known non-solar TNPDCL bills from entered details to the rupee, except documented taxes or rounding outside the model |
| Sizing engine | Recommended kWp never exceeds roof maximum or sanctioned-load maximum |
| Economics | Self-consumed and exported solar remain separate; no average-tariff shortcut |
| End-to-end | Five pilot addresses return roof results in under two seconds |
| Disclosure | Every Phase 1 result carries the official-feasibility disclaimer |

### Must verify before implementation

- Current TNPDCL tariff, billing-cycle treatment, solar export settlement, network charges, and subsidy rules.
- Which bill fields are consistently available and readable in supported TNPDCL bill formats.
- The self-consumption ranges used for each household profile.
- VIT's tariff, sanctioned demand, and consumption before attaching a rupee figure to its roof potential.

---

## 11. Demo scenario

1. **Physical potential:** A judge enters an address. PV Maps outlines the roof and says: “This roof can physically hold 6.4 kWp.”
2. **Bill reality:** Load a pre-validated TNPDCL bill scenario. PV Maps identifies the sanctioned load and consumption pattern.
3. **The reveal:** Slide through system sizes. The app shows self-used solar, low-value exports, annual savings, and payback at each size.
4. **Decision:** PV Maps highlights:

~~~text
Physical roof maximum:     6.4 kWp
Sanctioned-load maximum:   3.0 kWp
Recommended investment:    2.8 kWp

Reason:
Best expected bill savings per rupee.
Avoids oversizing into lower-value exported energy.
~~~

Close with:

> “The roof is not the recommendation. The bill is.”

For VIT, show “estimated physical rooftop potential: 2.1 MWp” only. Do not claim annual rupee savings without VIT's actual consumption and tariff data.

---

## 12. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Google already does roof potential | Medium | Demonstrate bill-specific sizing, not just roof area |
| Savings overstated without interval data | High | Use ranges and editable daytime-use profiles |
| Tariff or settlement rules change | Medium | Version every rule and show its effective date |
| Flat-roof segmentation error | Medium | Hand-correct demo roofs and report IoU honestly |
| Judge asks about grid approval | High | State clearly: official TNPDCL feasibility is required; Grid Passport is Phase 2 |
| Unverified VIT savings claim | Medium | Show physical MWp only until bill and tariff evidence are available |
| Scope expansion | Medium | Phase 1 non-goals are binding |

---

## 13. Competitive position

| Existing approach | What it solves | PV Maps difference |
|---|---|---|
| Google Solar API | Roof geometry and solar potential | Connects the physical roof to sanctioned load, actual billing, self-use, export, and economic sizing |
| MNRE / PM Surya Ghar calculators | Broad indicative calculations | Makes the size decision and assumptions visible |
| Installer calculators | Quote-oriented capacity and payback | Is willing to recommend a smaller, better-value system |
| Academic roof segmentation | Detects roofs in imagery | Treats segmentation as infrastructure rather than product novelty |

**Honest novelty:** Phase 1 is a meaningful product improvement, not a category-level claim. Its differentiator is transparent, bill-aware solar sizing for Tamil Nadu.

**Potential Phase 2 differentiation:** Grid Passport can become strongly differentiated only through real utility data, official application workflow integration, and a historical capacity ledger.

---

## 14. Sources

- [Google Solar API coverage](https://developers.google.com/maps/documentation/solar/coverage)
- [TNPDCL Unified Solar Rooftop Portal](https://www.tnebltd.gov.in/usrp/)
- [TNPDCL FAQ](https://www.tnebltd.gov.in/usrp/faq.xhtml)
- [TNPDCL rooftop-solar application form](https://www.tnebltd.gov.in/usrp/app_form-ncfa.xhtml)
- [TNPDCL GISS salient features and feasibility-report template](https://www.tnebltd.gov.in/usrp/Salientfeatures.pdf)
- [TNERC 2024 draft GISS regulations](https://energy.prayaspune.org/images/pdf/Draft_TNERC_GISS_regs_2024.pdf) — draft only; do not use as a live rule without Gazette confirmation
- [Mapping Solar Rooftop Potential in Chennai](https://energyconsortium.org/wp-content/uploads/2025/01/Working-Paper-3.pdf)
- [Solar Potential Analysis of Rooftops Using Satellite Imagery](https://arxiv.org/pdf/1812.11606)
