import { area } from "./format";

/**
 * Spatial & obstruction deduction ledger — FR-1.2 and FR-1.3, shown as
 * arithmetic rather than as a single number.
 *
 * Every line is real. Obstruction rows come from `obstruction_geojson`, whose
 * features carry `properties.label` and `properties.area_m2` written by the
 * pipeline (or by a person hand-correcting a pilot roof). The remainder between
 * those deductions and the usable area is the shading and setback allowance the
 * assumptions pack applies, so it is labelled as that rather than invented as a
 * specific parapet.
 *
 * FR-1.5: an unexplained subtraction cannot be argued with, which is the whole
 * reason this panel exists.
 */
export default function ObstructionLedger({ building, usableAreaM2 }) {
  if (!building) return null;

  const gross = building.roof_area_m2;
  const usable = usableAreaM2 ?? building.usable_area_m2;

  const features = building.obstruction_geojson?.features ?? [];
  const marked = features
    .map((f) => ({
      label: f?.properties?.label,
      m2: Number(f?.properties?.area_m2),
    }))
    .filter((o) => o.label && Number.isFinite(o.m2) && o.m2 > 0);

  const markedTotal = marked.reduce((t, o) => t + o.m2, 0);
  const remainder = Math.max(0, gross - usable - markedTotal);
  const pct = gross > 0 ? (usable / gross) * 100 : 0;

  return (
    <div>
      <p className="metric-label">Geospatial deduction audit</p>
      <p className="mono mt-0.5 text-code-mono text-ink-muted">
        {area(gross)} m² detected footprint
      </p>

      <table className="telemetry mt-2 text-code-mono">
        <tbody>
          {marked.map((o) => (
            <tr key={o.label}>
              <td className="num w-[68px] whitespace-nowrap !text-critical">−{o.m2.toFixed(1)} m²</td>
              <td className="capitalize text-ink-sub">{o.label}</td>
            </tr>
          ))}
          {remainder > 0.05 && (
            <tr>
              <td className="num w-[68px] whitespace-nowrap !text-critical">−{remainder.toFixed(1)} m²</td>
              <td className="text-ink-sub">Shading &amp; setback allowance</td>
            </tr>
          )}
        </tbody>
      </table>

      <div className="mt-2 flex items-baseline justify-between gap-2 border-t border-rail pt-2">
        <span className="caption">Net active solar roof</span>
        <span className="mono text-metric-label font-medium text-grid-deep">
          {area(usable)} m² ({pct.toFixed(1)}% usable)
        </span>
      </div>
    </div>
  );
}
