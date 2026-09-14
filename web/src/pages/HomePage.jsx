import { Suspense, lazy, useState } from "react";
import { useNavigate } from "react-router-dom";
import LocationSearch from "../components/LocationSearch";
import MeasuredRoofPanel from "../components/MeasuredRoofPanel";
import { api } from "../api/client";
import BillInputForm from "../components/BillInputForm";
import DaytimeUseForm from "../components/DaytimeUseForm";
import ErrorBoundary from "../components/ErrorBoundary";
import RoofAnalysisPanel from "../components/RoofAnalysisPanel";
import RoofCorrection from "../components/RoofCorrection";
import Chip from "../components/ui/Chip";
import ObstructionLedger from "../components/ui/ObstructionLedger";
import Panel from "../components/ui/Panel";
import Workstation from "../components/ui/Workstation";
import {
  NoStoredResultError,
  dataSource,
  getDataState,
  useDataState,
} from "../api/dataSource";
import { UsageProfileSchema } from "../schemas/sizing";

// Lazy: maplibre is ~700 kB and the flow works without it.
const RoofMap = lazy(() => import("../components/RoofMap"));

/**
 * ARCHITECTURE.md 4.1 — the primary browser flow, in order:
 * address → roof → correction → bill → daytime use → sizing run.
 *
 * Same workstation shell as the result screen, so the two read as one product:
 * spatial canvas behind, sizing rail left, analytical rail right.
 * ARCHITECTURE.md 4.2 — address search is the first useful interaction and no
 * login wall appears before the roof result.
 */
export default function HomePage() {
  const navigate = useNavigate();
  const { mode } = useDataState();
  const offline = mode === "FALLBACK";

  const [address, setAddress] = useState(null);
  const [building, setBuilding] = useState(null);
  const [usableAreaM2, setUsableAreaM2] = useState(null);

  // Live measurement, for anywhere that is not a seeded pilot roof.
  const [measuring, setMeasuring] = useState(false);
  const [measured, setMeasured] = useState(null); // RoofAtResult
  const [chosenIndex, setChosenIndex] = useState(null);
  const [measureError, setMeasureError] = useState(null);
  const [form, setForm] = useState({ modifiers: [], occupancy: "PARTIAL" });
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);

  // A measured roof advances the flow exactly as a seeded one does -- the
  // optimiser only ever needed a usable area, and where it came from is a
  // provenance question, not a control-flow one.
  const chosen =
    measured && chosenIndex != null ? measured.candidates[chosenIndex] : null;
  const haveRoof = Boolean(building) || Boolean(chosen);
  const step = !haveRoof ? 1 : form.monthly_units_kwh ? 3 : 2;
  const stepTitle = ["Locate roof", "Bill profile", "Daytime load"][step - 1];

  /** Measure the roof under a point on the GPU. Used for any non-pilot place. */
  async function measureAt(lat, lon) {
    setMeasuring(true);
    setMeasureError(null);
    setMeasured(null);
    setChosenIndex(null);
    setBuilding(null);
    try {
      const r = await api.roofAt(lat, lon);
      setMeasured(r);
      setChosenIndex(r.chosen);
      // Only adopt the area when SAM2 actually settled on something plausible.
      // r.chosen is null when every outline fell outside the roof window, and
      // silently taking candidates[0] there is how a city block becomes a
      // household's roof area.
      setUsableAreaM2(
        r.chosen != null ? Math.round(r.candidates[r.chosen].area_m2) : null,
      );
      if (r.warning) setMeasureError(r.warning);
    } catch (e) {
      setMeasureError(
        e?.status === 503
          ? "Roof measurement is unavailable right now. You can still type a roof area below."
          : "Could not measure that roof. Try dropping the pin on the roof itself.",
      );
      setUsableAreaM2(null);
    } finally {
      setMeasuring(false);
    }
  }

  function pickCandidate(i) {
    if (!measured?.candidates?.[i]) return;
    setChosenIndex(i);
    setUsableAreaM2(Math.round(measured.candidates[i].area_m2));
    setMeasureError(null);
  }

  async function selectAddress(a) {
    setAddress(a);
    setBuilding(null);
    setUsableAreaM2(null);
    setMeasured(null);
    setChosenIndex(null);
    setMeasureError(null);
    setSubmitError(null);

    // A seeded pilot roof is the better answer where one exists: its area was
    // checked by a person and it carries a precomputed pvlib yield.
    if (a.address?.building_id) {
      try {
        const b = await dataSource.getBuilding(a.address.building_id);
        setBuilding(b);
        setUsableAreaM2(Math.round(b.usable_area_m2));
        return;
      } catch (e) {
        setSubmitError(
          e instanceof NoStoredResultError
            ? "That pilot roof is not in the offline bundle — measuring it live instead."
            : "Could not load the stored roof — measuring it live instead.",
        );
      }
    }
    await measureAt(a.lat, a.lon);
  }

  async function locateFromBillAddress(addrStr) {
    if (!addrStr) return;
    try {
      const hits = await api.geocode(addrStr);
      if (hits && hits.length > 0) {
        await selectAddress({
          kind: "MAPPED",
          label: hits[0].display_name,
          lat: hits[0].lat,
          lon: hits[0].lon,
        });
      }
    } catch (e) {
      console.warn("Could not geocode bill address:", e);
    }
  }

  async function submit(e) {
    e.preventDefault();
    setSubmitError(null);

    // A measured roof travels as `traced_roof` -- the API branch that already
    // exists for hand-drawn outlines. roof_area_m2 and usable_area_m2 are the
    // same figure here because SAM2 returns a footprint, not a usable plane:
    // obstructions and the parapet setback have NOT been subtracted, which is
    // why the panel calls it a detected area rather than a usable one.
    const measuredRoof =
      !building && chosen
        ? {
            lat: measured.lat,
            lon: measured.lon,
            roof_area_m2: Math.round(chosen.area_m2),
            usable_area_m2: usableAreaM2 ?? Math.round(chosen.area_m2),
          }
        : undefined;

    const parsed = UsageProfileSchema.safeParse({
      ...form,
      building_id: building?.id ?? "",
      traced_roof: measuredRoof,
    });
    if (!parsed.success) {
      setErrors(parsed.error.flatten().fieldErrors);
      return;
    }
    setErrors({});
    setSubmitting(true);
    try {
      // FR-1.5 — send an override ONLY when the household actually moved the
      // number. The field is seeded with the detected area so the input is not
      // empty; passing that back unchanged made every run report
      // usable_area_source=USER_CORRECTED, claiming a correction nobody made.
      // Only a seeded roof has a "detected" figure to differ from. A measured
      // roof carries its area in traced_roof, so sending an override too would
      // label it USER_CORRECTED for a correction nobody made.
      const detected = building ? Math.round(building.usable_area_m2) : null;
      const corrected =
        usableAreaM2 != null && detected != null && usableAreaM2 !== detected
          ? usableAreaM2
          : undefined;

      // The API's contract is "exactly one of building_id and traced_roof",
      // and it enforces that with min_length=1 on building_id -- so an empty
      // string is a 422, not a stand-in for absent. Zod defaults it to "" to
      // keep the field present for the form, which means it has to be stripped
      // here rather than sent as a falsy value the server will reject.
      const { building_id: bid, ...withoutBuilding } = parsed.data;
      const payload = bid ? parsed.data : withoutBuilding;

      const rec = await dataSource.createSizingRun({
        ...payload,
        usable_area_m2_override: corrected,
      });

      // Read the mode AFTER the call: a live request that timed out switches the
      // session to stored data on its way through, and the result screen has to
      // know which of the two it is holding.
      const servedOffline = getDataState().mode === "FALLBACK";

      // The run id is an opaque short-lived token (ARCHITECTURE.md 8), so it is
      // safe in the URL. Geometry travels in router state so the workstation can
      // draw its canvas without a second fetch — and still renders without it.
      navigate(`/results/${rec.run_id ?? "preview"}`, {
        state: {
          recommendation: rec,
          building,
          address,
          offline: servedOffline,
          corrected: corrected != null,
        },
      });
    } catch (err) {
      setSubmitError(
        err instanceof NoStoredResultError
          ? "This pilot roof has no stored offline result. PV Maps publishes a " +
              "physical rooftop potential for it but no rupee figures, because the " +
              "consumption and tariff behind those figures are not known."
          : "Could not calculate a recommendation. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  // The map is a 700 kB lazy chunk. If it fails to arrive, the flow must carry
  // on without it — vite.config.js splits it out on exactly that promise.
  // ALWAYS mounted, address or not. It used to appear only once a parcel
  // resolved, which made the first screen a form with a grey rectangle on it
  // and gave no way to point at a roof the search could not name. Starting over
  // Vellore means the user can pan and click before typing anything.
  const mapCentre = address ? [address.lon, address.lat] : [79.1325, 12.9202];
  const map = (
    <ErrorBoundary quiet>
      <Suspense fallback={null}>
        <RoofMap
          building={building}
          center={mapCentre}
          candidates={measured?.candidates ?? null}
          chosenIndex={chosenIndex}
          layout={measured?.layout ?? null}
          onPickCandidate={pickCandidate}
          onPickPoint={measuring ? null : measureAt}
          fill
        />
      </Suspense>
    </ErrorBoundary>
  );

  const inlineMap = (
    <ErrorBoundary quiet>
      <Suspense
        fallback={
          <div className="h-[300px] rounded-lg border border-hairline bg-well" />
        }
      >
        <RoofMap
          building={building}
          center={mapCentre}
          label={address?.label}
          candidates={measured?.candidates ?? null}
          chosenIndex={chosenIndex}
          layout={measured?.layout ?? null}
          onPickCandidate={pickCandidate}
          onPickPoint={measuring ? null : measureAt}
        />
      </Suspense>
    </ErrorBoundary>
  );

  return (
    <form onSubmit={submit}>
      {/* Step strip — the same bar the result screen carries. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-hairline bg-surface px-4 py-1.5 sm:px-5">
        <span className="metric-label">
          Step {step} of 4 · {stepTitle}
        </span>
        <span className="flex gap-0.5" aria-hidden="true">
          {[1, 2, 3, 4].map((i) => (
            <span
              key={i}
              className={`h-1 w-6 rounded-sm ${i <= step ? "bg-ink" : "bg-hairline"}`}
            />
          ))}
        </span>
        <span className="flex min-w-0 flex-wrap items-center gap-1.5 sm:ml-auto">
          {offline && (
            <Chip tone="warn" dot>
              Bundled pilot data
            </Chip>
          )}
          {measuring ? (
            <Chip tone="warn" dot>
              Measuring roof…
            </Chip>
          ) : building ? (
            <Chip tone="ok" dot>
              Pilot roof
            </Chip>
          ) : chosen ? (
            <Chip tone="ok" dot>
              Roof measured
            </Chip>
          ) : (
            <Chip tone="neutral">Awaiting parcel</Chip>
          )}
        </span>
      </div>

      <Workstation
        canvas={map}
        inlineCanvas={inlineMap}
        emptyLabel="No parcel selected"
        left={
          <>
            <Panel
              floating
              title="Find a roof"
              aside={<Chip tone="neutral">India</Chip>}
            >
              <LocationSearch
                onPick={selectAddress}
                selected={address}
                busy={measuring}
              />
            </Panel>

            {!address && (
              <div className="hud px-3 py-2">
                <p className="metric-label !text-solar-deep">
                  Core sizing metric
                </p>
                <p className="mt-1 font-display text-body-sm leading-5 text-ink">
                  “Every solar calculator tells you what a roof can hold. PV
                  Maps tells you what a bill can use.”
                </p>
                <p className="mt-2 border-t border-well pt-2 text-code-mono leading-4 text-ink-muted">
                  Search any address, or tap a roof on the map. Roofs are
                  measured from satellite imagery when you pick one — the five
                  pilot roofs are the exception and come pre-checked.
                </p>
              </div>
            )}

            {building && <RoofAnalysisPanel building={building} />}

            {!building && (measuring || measured || measureError) && (
              <MeasuredRoofPanel
                measuring={measuring}
                measured={measured}
                chosenIndex={chosenIndex}
                onPick={pickCandidate}
                error={measureError}
              />
            )}

            {building && (
              <Panel floating title="Spatial deduction ledger">
                <ObstructionLedger
                  building={building}
                  usableAreaM2={usableAreaM2}
                />
              </Panel>
            )}

            {building && (
              <RoofCorrection
                building={building}
                usableAreaM2={usableAreaM2}
                onChange={setUsableAreaM2}
              />
            )}
          </>
        }
        right={
          <>
            <BillInputForm
              value={form}
              onChange={setForm}
              errors={errors}
              onLocateAddress={locateFromBillAddress}
            />
            <DaytimeUseForm value={form} onChange={setForm} />

            <div className="hud px-3 py-2">
              <button
                type="submit"
                disabled={!haveRoof || submitting}
                className="btn w-full"
              >
                {submitting
                  ? "Calculating…"
                  : "Size this roof against the bill"}
              </button>
              <p className="mt-1.5 text-code-mono leading-4 text-ink-muted">
                {!haveRoof
                  ? "Search an address, or tap a roof on the map, so we have an area to size against."
                  : offline
                    ? "Offline: the optimiser cannot run, so this returns the stored scenario bundled for this roof rather than a calculation over your figures."
                    : "Runs the optimiser over every allowed size and returns the whole comparison curve."}
              </p>
              {submitError && (
                <p className="notice notice-critical mt-2">{submitError}</p>
              )}
            </div>
          </>
        }
      />
    </form>
  );
}
