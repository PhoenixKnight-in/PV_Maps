import { Suspense, lazy, useState } from "react";
import { useNavigate } from "react-router-dom";
import AddressSearch from "../components/AddressSearch";
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
  const [form, setForm] = useState({ modifiers: [], occupancy: "PARTIAL" });
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);

  const step = !building ? 1 : form.monthly_units_kwh ? 3 : 2;
  const stepTitle = ["Locate roof", "Bill profile", "Daytime load"][step - 1];

  async function selectAddress(a) {
    setAddress(a);
    setBuilding(null);
    setUsableAreaM2(null);
    setSubmitError(null);
    if (!a.building_id) return;
    try {
      const b = await dataSource.getBuilding(a.building_id);
      setBuilding(b);
      setUsableAreaM2(Math.round(b.usable_area_m2));
    } catch (e) {
      setSubmitError(
        e instanceof NoStoredResultError
          ? "That roof is not in the offline pilot bundle. Pick another address."
          : "Could not load that roof.",
      );
    }
  }

  async function submit(e) {
    e.preventDefault();
    setSubmitError(null);

    const parsed = UsageProfileSchema.safeParse({ ...form, building_id: building?.id ?? "" });
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
      const detected = building ? Math.round(building.usable_area_m2) : null;
      const corrected =
        usableAreaM2 != null && detected != null && usableAreaM2 !== detected
          ? usableAreaM2
          : undefined;

      const rec = await dataSource.createSizingRun({
        ...parsed.data,
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
  const map = address ? (
    <ErrorBoundary quiet>
      <Suspense fallback={null}>
        <RoofMap building={building} center={[address.lon, address.lat]} fill />
      </Suspense>
    </ErrorBoundary>
  ) : null;

  const inlineMap = address ? (
    <ErrorBoundary quiet>
      <Suspense
        fallback={<div className="h-[300px] rounded-lg border border-hairline bg-well" />}
      >
        <RoofMap
          building={building}
          center={[address.lon, address.lat]}
          label={address.display_name}
        />
      </Suspense>
    </ErrorBoundary>
  ) : null;

  return (
    <form onSubmit={submit}>
      {/* Step strip — the same bar the result screen carries. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-hairline bg-surface px-4 py-1.5 sm:px-5">
        <span className="metric-label">
          Step {step} of 4 · {stepTitle}
        </span>
        <span className="flex gap-0.5" aria-hidden="true">
          {[1, 2, 3, 4].map((i) => (
            <span key={i} className={`h-1 w-6 rounded-sm ${i <= step ? "bg-ink" : "bg-hairline"}`} />
          ))}
        </span>
        <span className="flex min-w-0 flex-wrap items-center gap-1.5 sm:ml-auto">
          {offline && (
            <Chip tone="warn" dot>
              Bundled pilot data
            </Chip>
          )}
          {building ? (
            <Chip tone="ok" dot>
              Roof extracted
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
              title="Parcel locator"
              aside={<Chip tone="neutral">Vellore Ward 12</Chip>}
            >
              <AddressSearch onSelect={selectAddress} selected={address} />
            </Panel>

            {!address && (
              <div className="hud px-3 py-2">
                <p className="metric-label !text-solar-deep">Core sizing metric</p>
                <p className="mt-1 font-display text-body-sm leading-5 text-ink">
                  “Every solar calculator tells you what a roof can hold. PV Maps
                  tells you what a bill can use.”
                </p>
                <p className="mt-2 border-t border-well pt-2 text-code-mono leading-4 text-ink-muted">
                  Search a pilot address to load its extracted roof. Roof data is
                  precomputed; nothing is segmented live.
                </p>
              </div>
            )}

            {building && <RoofAnalysisPanel building={building} />}

            {building && (
              <Panel floating title="Spatial deduction ledger">
                <ObstructionLedger building={building} usableAreaM2={usableAreaM2} />
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
            <BillInputForm value={form} onChange={setForm} errors={errors} />
            <DaytimeUseForm value={form} onChange={setForm} />

            <div className="hud px-3 py-2">
              <button type="submit" disabled={!building || submitting} className="btn w-full">
                {submitting ? "Calculating…" : "Size this roof against the bill"}
              </button>
              <p className="mt-1.5 text-code-mono leading-4 text-ink-muted">
                {!building
                  ? "Pick an address first — we need the roof before we can size anything."
                  : offline
                    ? "Offline: the optimiser cannot run, so this returns the stored scenario bundled for this roof rather than a calculation over your figures."
                    : "Runs the optimiser over every allowed size and returns the whole comparison curve."}
              </p>
              {submitError && <p className="notice notice-critical mt-2">{submitError}</p>}
            </div>
          </>
        }
      />
    </form>
  );
}
