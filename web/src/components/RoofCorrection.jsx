import Panel from "./ui/Panel";
import Chip from "./ui/Chip";
import { area, kwp } from "./ui/format";

/**
 * ARCHITECTURE.md 4.1 step 3 — let the user adjust the outline or obstruction
 * assumptions.
 *
 * Segmentation on flat Indian roofs at z=20 is imperfect, and the PRD says to
 * report that honestly rather than hide it. Letting the user correct the usable
 * area is cheaper than pretending the mask is right, and it makes the demo
 * robust to one bad polygon.
 */
export default function RoofCorrection({ building, usableAreaM2, onChange }) {
  if (!building) return null;

  const detected = building.usable_area_m2;
  const corrected = usableAreaM2 ?? Math.round(detected);
  const wasChanged = Math.abs(corrected - detected) > 1;
  const band = building.roof_max_kwp_band;

  return (
    <Panel
      floating
      title="Roof extraction"
      aside={
        <Chip tone={building.confidence >= 0.75 ? "ok" : "warn"} dot>
          Confidence {(building.confidence * 100).toFixed(0)}%
        </Chip>
      }
    >
      <dl className="cell-grid grid-cols-2">
        <div className="cell">
          <dt className="caption">Detected footprint</dt>
          <dd className="metric-row mt-1">
            <span className="metric-sm">{area(building.roof_area_m2)}</span>
            <span className="unit">m²</span>
          </dd>
        </div>
        <div className="cell">
          <dt className="caption">Roof allows</dt>
          <dd>
            <span className="metric-row mt-1">
              <span className="metric-sm">{kwp(building.roof_max_kwp)}</span>
              <span className="unit">kWp</span>
            </span>
            {band && band.lo !== band.hi && (
              <span className="band">
                {kwp(band.lo)} to {kwp(band.hi)}
              </span>
            )}
          </dd>
        </div>
      </dl>

      <div className="mt-2 flex items-center gap-2">
        <label htmlFor="usable" className="caption shrink-0">
          Usable roof (m²)
        </label>
        <input
          id="usable"
          type="number"
          min="0"
          className="field w-24"
          value={corrected}
          onChange={(e) => onChange(Number(e.target.value))}
        />
        {wasChanged && <Chip tone="sky">Your figure</Chip>}
      </div>

      <p className="mt-1.5 text-code-mono leading-4 text-ink-muted">
        {wasChanged
          ? "Using your figure instead of ours. The result will say so."
          : "Adjust if we missed a water tank, stairhead or parapet. The calculation uses the conservative end of the band."}
      </p>

      {/* TODO: polygon vertex editing. The numeric override covers the demo and
          is the part that actually changes the answer. */}
    </Panel>
  );
}
