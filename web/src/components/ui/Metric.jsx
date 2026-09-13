import { inr } from "./format";

const TONE = {
  default: "text-ink",
  sky: "text-sky-deep",
  solar: "text-solar-deep",
  grid: "text-grid-deep",
  critical: "text-critical",
};

const SIZE = { lg: "metric-lg", md: "metric", sm: "metric-sm" };

/**
 * A data pair: caption label above, primary value beneath, unit explicitly
 * tagged in subtle ink beside it.
 *
 * There is deliberately no `Metric` variant that accepts a range. A banded
 * figure must render its band, so that lives in `BandedMetric` and cannot be
 * forgotten at a call site.
 */
export function Metric({ label, value, unit, hint, size = "md", tone = "default", className = "" }) {
  return (
    <div className={className}>
      <dt className="caption">{label}</dt>
      <dd>
        <span className="metric-row mt-1">
          <span className={`${SIZE[size]} ${TONE[tone]}`}>{value}</span>
          {unit && <span className="unit">{unit}</span>}
        </span>
        {hint && <span className="mt-1 block text-code-mono leading-4 text-ink-muted">{hint}</span>}
      </dd>
    </div>
  );
}

/**
 * Renders one banded figure. There is no variant that takes a bare number.
 *
 * NFR "Honesty" / ARCHITECTURE.md 7: an inferred figure may not be displayed
 * as precise fact, so the band is part of the component contract.
 */
export function BandedMetric({
  label,
  range,
  format = inr,
  unit = "",
  hint,
  size = "md",
  tone = "default",
  className = "",
}) {
  const certain = range.lo === range.hi;
  return (
    <div className={className}>
      <dt className="caption">{label}</dt>
      <dd>
        <span className="metric-row mt-1">
          <span className={`${SIZE[size]} ${TONE[tone]}`}>
            {format(certain ? range.lo : (range.lo + range.hi) / 2)}
          </span>
          {unit && <span className="unit">{unit}</span>}
        </span>
        {!certain && (
          <span className="band">
            {format(range.lo)} to {format(range.hi)}
          </span>
        )}
        {hint && <span className="mt-1 block text-code-mono leading-4 text-ink-muted">{hint}</span>}
      </dd>
    </div>
  );
}
