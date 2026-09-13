import Panel from "./ui/Panel";
import Chip from "./ui/Chip";
import { area, kwp } from "./ui/format";

/**
 * The roof as the primary spatial object — FR-1.3, FR-1.4, FR-1.6.
 *
 * Every field here exists on `BuildingOut`: footprint and usable area, the
 * conservative roof ceiling and its honest band, typology, segmentation
 * confidence, and which yield basis drove it.
 *
 * The reference screen also shows azimuth, GHI, tilt and a shadow-free
 * percentage. `BuildingOut` carries none of those, so they are absent rather
 * than invented — FR-2.4 says to use documented physical assumptions, not to
 * decorate the panel with numbers the pipeline never produced.
 */
export default function RoofAnalysisPanel({ building }) {
  if (!building) return null;

  const band = building.roof_max_kwp_band;
  const y = building.annual_yield_kwh_per_kwp;
  const obstructions = building.obstruction_geojson?.features?.length ?? 0;
  const pct = building.roof_area_m2 > 0 ? (building.usable_area_m2 / building.roof_area_m2) * 100 : 0;

  return (
    <Panel
      floating
      title="Roof analysis"
      aside={
        <span className="flex items-center gap-1.5">
          <Chip tone="neutral">{building.typology}</Chip>
          <Chip tone={building.confidence >= 0.75 ? "ok" : "warn"} dot>
            IoU {building.confidence.toFixed(2)}
          </Chip>
        </span>
      }
      bodyClass="!p-0"
    >
      <dl className="cell-grid grid-cols-2 !rounded-none !border-0 !border-b">
        <div className="cell">
          <dt className="caption">Detected footprint</dt>
          <dd className="metric-row mt-1">
            <span className="metric">{area(building.roof_area_m2)}</span>
            <span className="unit">m²</span>
          </dd>
        </div>
        <div className="cell">
          <dt className="caption">Usable roof plane</dt>
          <dd className="metric-row mt-1">
            <span className="metric text-grid-deep">{area(building.usable_area_m2)}</span>
            <span className="unit">m²</span>
          </dd>
          <dd className="mono mt-0.5 text-code-mono text-ink-subtle">
            {pct.toFixed(1)}% of footprint
          </dd>
        </div>
      </dl>

      <dl className="cell-grid grid-cols-2 !rounded-none !border-0 !border-b">
        <div className="cell">
          <dt className="caption">Roof solar ceiling</dt>
          <dd>
            <span className="metric-row mt-1">
              <span className="metric text-solar-deep">{kwp(building.roof_max_kwp)}</span>
              <span className="unit">kWp</span>
            </span>
            {band && band.lo !== band.hi && (
              <span className="band">
                {kwp(band.lo)} to {kwp(band.hi)} kWp may fit
              </span>
            )}
          </dd>
        </div>
        <div className="cell">
          <dt className="caption">Specific yield</dt>
          <dd>
            <span className="metric-row mt-1">
              <span className="metric-sm">{Math.round(y.value).toLocaleString("en-IN")}</span>
              <span className="unit">kWh/kWp/yr</span>
            </span>
            {y.lo !== y.hi && (
              <span className="band">
                {Math.round(y.lo).toLocaleString("en-IN")} to{" "}
                {Math.round(y.hi).toLocaleString("en-IN")}
              </span>
            )}
          </dd>
        </div>
      </dl>

      <div className="flex flex-wrap items-center gap-1.5 px-3 py-2">
        <Chip tone={building.yield_source === "BUILDING" ? "ok" : "warn"} dot>
          {building.yield_source === "BUILDING" ? "Roof-specific pvlib run" : "Regional yield band"}
        </Chip>
        {obstructions > 0 && (
          <Chip tone="critical">
            {obstructions} obstruction{obstructions === 1 ? "" : "s"} marked
          </Chip>
        )}
        {building.analysis_version && (
          <Chip tone="neutral">{building.analysis_version}</Chip>
        )}
      </div>

      {y.note && (
        <p className="border-t border-well px-3 py-2 text-code-mono leading-4 text-ink-muted">
          {y.note}
        </p>
      )}
    </Panel>
  );
}
