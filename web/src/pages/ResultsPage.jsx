import { Suspense, lazy, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import AssumptionsPanel from "../components/AssumptionsPanel";
import CandidateTable from "../components/CandidateTable";
import EconomicsBreakdown from "../components/EconomicsBreakdown";
import ErrorBoundary from "../components/ErrorBoundary";
import { OfflineResultNotice } from "../components/OfflineNotice";
import RegulatoryBar from "../components/RegulatoryBar";
import RoofAnalysisPanel from "../components/RoofAnalysisPanel";
import SizingCurve from "../components/SizingCurve";
import Chip from "../components/ui/Chip";
import CapacityTriCard from "../components/ui/CapacityTriCard";
import EnergySplitBar from "../components/ui/EnergySplitBar";
import ObstructionLedger from "../components/ui/ObstructionLedger";
import Panel from "../components/ui/Panel";
import SizingScrubber from "../components/ui/SizingScrubber";
import Workstation from "../components/ui/Workstation";
import { area, kwp } from "../components/ui/format";

const RoofMap = lazy(() => import("../components/RoofMap"));

/**
 * The Bill-to-Roof Optimiser result — the same workstation shell the intake
 * screen uses, so the two read as one product.
 *
 * Hierarchy: recommendation, the two ceilings that produced it, the binding
 * constraint, annual economics, energy split, the value curve, assumptions,
 * regulatory disclosure.
 *
 * ARCHITECTURE.md 10 item 5 requires this screen to render with no map, no
 * imagery and no network beyond the sizing response. The canvas is therefore a
 * backdrop that appears only when building geometry came through with the
 * result; without it every number still renders.
 *
 * The recommendation arrives in router state, not from a fetch. There is no
 * `GET /v1/sizing-runs/{id}` and Phase 1 does not need one: the stored run is a
 * reproducibility record, holds only inputs and a reduced curve, and is
 * deliberately short-lived.
 */
export default function ResultsPage() {
  const { state } = useLocation();
  const recommendation = state?.recommendation;
  const building = state?.building;
  const address = state?.address;
  /** Served from the bundled pilot data rather than the optimiser — set by the
   *  intake screen at the moment of the call, not read live, so a connection
   *  that recovers afterwards cannot relabel a stored result as a live one. */
  const offline = state?.offline === true;

  const [activeKwp, setActiveKwp] = useState(null);

  if (!recommendation) {
    return (
      <div className="p-4">
        <Panel title="That result is no longer on this page">
          <p className="text-body-sm leading-5 text-ink-sub">
            Results are calculated on demand and are not stored for later
            retrieval, so a refreshed or shared link cannot bring one back. Your
            bill details were never kept.
          </p>
          <Link to="/" className="btn mt-3">
            Start again
          </Link>
        </Panel>
      </div>
    );
  }

  const r = recommendation;
  const curve = r.curve ?? [];
  const selected =
    curve.find((c) => c.kwp === activeKwp) ??
    r.recommended ??
    curve[curve.length - 1] ??
    null;
  const isRecommended = !!r.recommended && selected?.kwp === r.recommended.kwp;

  if (r.verdict === "NO_CAPACITY") {
    return (
      <>
        {offline && <OfflineResultNotice corrected={state?.corrected} />}
        <div className="p-4">
          <Panel title="There is no installable system here">
            <p className="text-body-sm leading-5 text-ink-sub">
              Between the usable roof area and the sanctioned load, there is not
              enough room for even the smallest standard system. Raising the
              sanctioned load on your connection would change this.
            </p>
            <Link to="/" className="btn mt-3">
              Try another address
            </Link>
          </Panel>
        </div>
        {/* PRD 5.2 — the disclosure is required on EVERY result, including the
            ones that recommend nothing. */}
        <RegulatoryBar recommendation={r} />
      </>
    );
  }

  // ARCHITECTURE.md 10 item 5: this screen renders with no map at all. The
  // boundary is what makes that true when the chunk fails rather than when the
  // geometry is simply absent.
  const map = building ? (
    <ErrorBoundary quiet>
      <Suspense fallback={null}>
        <RoofMap
          building={building}
          center={address ? [address.lon, address.lat] : null}
          fill
        />
      </Suspense>
    </ErrorBoundary>
  ) : null;

  const inlineMap = building ? (
    <ErrorBoundary quiet>
      <Suspense
        fallback={
          <div className="h-[300px] rounded-lg border border-hairline bg-well" />
        }
      >
        <RoofMap
          building={building}
          center={address ? [address.lon, address.lat] : null}
          label={address?.display_name}
        />
      </Suspense>
    </ErrorBoundary>
  ) : null;

  return (
    <>
      {/* Step strip — identical bar to the intake screen. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-hairline bg-surface px-4 py-1.5 sm:px-5">
        <span className="metric-label">Step 4 of 4 · Results</span>
        <span className="flex gap-0.5" aria-hidden="true">
          {[1, 2, 3, 4].map((i) => (
            <span key={i} className="h-1 w-6 rounded-sm bg-ink" />
          ))}
        </span>
        <span className="flex min-w-0 flex-wrap items-center gap-1.5 sm:ml-auto">
          {offline && (
            <Chip tone="warn" dot>
              Stored scenario
            </Chip>
          )}
          <Chip tone="neutral">Tariff {r.tariff_version}</Chip>
          <Chip tone={r.assumptions_verified ? "ok" : "warn"} dot>
            {r.assumptions_verified ? "Rules verified" : "Provisional rules"}
          </Chip>
        </span>
      </div>

      {offline && <OfflineResultNotice corrected={state?.corrected} />}

      <Workstation
        canvas={map}
        inlineCanvas={inlineMap}
        left={
          <>
            {address && (
              <div className="hud flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                <span className="chip-dot bg-sky" aria-hidden="true" />
                <span className="text-body-sm font-medium text-ink">
                  {address.display_name}
                </span>
                <span className="mono text-code-mono text-ink-muted">
                  {address.lat.toFixed(4)}° N, {address.lon.toFixed(4)}° E
                </span>
              </div>
            )}

            <Panel
              floating
              title="Capacity comparison audit"
              aside={<Chip tone="neutral">FR-5</Chip>}
            >
              <CapacityTriCard recommendation={r} />
            </Panel>

            {building && <RoofAnalysisPanel building={building} />}

            {building && (
              <Panel floating title="Spatial deduction ledger">
                <ObstructionLedger
                  building={building}
                  usableAreaM2={r.usable_area_m2}
                />
              </Panel>
            )}

            <div className="hud flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <div>
                <p className="caption">Subsidy applied</p>
                <p className="mono mt-0.5 text-metric-label text-ink">
                  PM Surya Ghar · {r.subsidy_version}
                </p>
              </div>
              <Link to="/" className="btn-secondary">
                Run another address
              </Link>
            </div>
          </>
        }
        right={
          <>
            <Panel
              floating
              title="Bill-to-generation alignment"
              aside={
                <Chip tone="neutral">{kwp(r.feasible_max_kwp)} kWp cap</Chip>
              }
              bodyClass="!p-0"
            >
              <dl className="cell-grid grid-cols-3 !rounded-none !border-0 !border-b">
                <div className="cell">
                  <dt className="caption">Usable roof</dt>
                  <dd className="mono mt-1 text-metric-label text-ink">
                    {area(r.usable_area_m2)} m²
                  </dd>
                  <dd className="mono mt-0.5 text-code-mono text-ink-subtle">
                    {r.usable_area_source === "USER_CORRECTED"
                      ? "Your figure"
                      : r.usable_area_source === "USER_TRACED"
                        ? "Measured live"
                        : "Segmented"}
                  </dd>
                </div>
                <div className="cell">
                  <dt className="caption">Yield basis</dt>
                  <dd className="mono mt-1 text-metric-label text-ink">
                    {r.yield_source === "BUILDING" ? "This roof" : "Regional"}
                  </dd>
                  <dd className="mono mt-0.5 text-code-mono text-ink-subtle">
                    {r.assumptions_version}
                  </dd>
                </div>
                <div className="cell">
                  <dt className="caption">Binding limit</dt>
                  <dd className="mono mt-1 text-metric-label text-ink">
                    {r.binding_constraint === "SANCTIONED_LOAD"
                      ? "Load"
                      : r.binding_constraint === "ROOF"
                        ? "Roof"
                        : "Both"}
                  </dd>
                  <dd className="mono mt-0.5 text-code-mono text-ink-subtle">
                    {kwp(r.feasible_max_kwp)} kWp
                  </dd>
                </div>
              </dl>

              {selected && (
                <div className="border-b border-well p-3">
                  <EnergySplitBar
                    generation={selected.annual_generation}
                    selfConsumed={selected.annual_self_consumed_kwh}
                    exported={selected.annual_exported_kwh}
                    kwpLabel={`${kwp(selected.kwp)} kWp system`}
                  />
                </div>
              )}

              <div className="p-3">
                <SizingScrubber
                  curve={curve}
                  value={selected?.kwp}
                  onChange={setActiveKwp}
                  recommendedKwp={r.recommended?.kwp}
                  feasibleMax={r.feasible_max_kwp}
                />
                {/* Only when there IS a recommendation to return to. On
                    NOT_ECONOMIC the API sends `recommended: null`, and inviting
                    the household back to a size that was never recommended
                    printed "We recommend NaN kWp". */}
                {!isRecommended && selected && r.recommended && (
                  <p className="notice notice-warn mt-2">
                    Showing {kwp(selected.kwp)} kWp. We recommend{" "}
                    {kwp(r.recommended.kwp)} kWp —{" "}
                    <button
                      type="button"
                      className="underline"
                      onClick={() => setActiveKwp(r.recommended?.kwp ?? null)}
                    >
                      go back to it
                    </button>
                    .
                  </p>
                )}
              </div>
            </Panel>

            <SizingCurve recommendation={r} activeKwp={selected?.kwp} />
            <CandidateTable recommendation={r} />
          </>
        }
      />

      {/* Economics and provenance, full width beneath the workstation. */}
      <div className="grid gap-3 px-4 pb-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <EconomicsBreakdown recommendation={r} />
        <AssumptionsPanel recommendation={r} />
      </div>

      <RegulatoryBar recommendation={r} />
    </>
  );
}
