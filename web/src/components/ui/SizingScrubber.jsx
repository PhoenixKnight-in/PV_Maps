import { kwp } from "./format";

/**
 * PRD 11, demo beat 3 — "Slide through system sizes. The app shows self-used
 * solar, low-value exports, annual savings, and payback at each size."
 *
 * The scrubber selects among the candidates the API already returned in
 * `curve`. It does not interpolate and it does not compute: every position on
 * this track is a size the optimiser actually evaluated, so a figure read off
 * it is the same figure the engine produced.
 */
export default function SizingScrubber({ curve, value, onChange, recommendedKwp, feasibleMax }) {
  if (!curve?.length) return null;

  const index = Math.max(
    0,
    curve.findIndex((c) => c.kwp === value),
  );
  const min = curve[0].kwp;
  const max = curve[curve.length - 1].kwp;

  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <span className="metric-label">Dynamic system sizing scrubber</span>
        <span
          className={`chip ${
            recommendedKwp != null && value === recommendedKwp
              ? "chip-warn"
              : "chip-neutral"
          }`}
        >
          {kwp(value)} kWp
        </span>
      </div>

      <input
        type="range"
        min={0}
        max={curve.length - 1}
        step={1}
        value={index}
        onChange={(e) => onChange(curve[Number(e.target.value)].kwp)}
        aria-label="System size"
        className="mt-2 h-1.5 w-full cursor-pointer appearance-none rounded-sm bg-hairline accent-solar"
      />

      {/* On a NOT_ECONOMIC verdict the optimiser recommends nothing and the API
          sends `recommended: null` — PRD G2's honest zero. Formatting that as a
          number printed "NaN kWp (recommended)"; the absence of a recommendation
          is the answer, so the marker is omitted rather than faked. */}
      <div className="mt-1.5 flex justify-between font-mono text-code-mono text-ink-muted">
        <span>{kwp(min)} kWp (min)</span>
        {recommendedKwp != null && (
          <span className="text-solar-deep">{kwp(recommendedKwp)} kWp (recommended)</span>
        )}
        <span>{kwp(feasibleMax)} kWp (cap)</span>
        <span>{kwp(max)} kWp (max)</span>
      </div>
    </div>
  );
}
