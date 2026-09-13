import { kwh } from "./format";

/**
 * FR-4.2 — self-consumed and exported kWh as separate numbers, here also as
 * separate areas.
 *
 * The split is the argument for recommending less than the roof allows: solar
 * used inside the house displaces an imported unit at the marginal slab rate,
 * and an exported unit does not. Emerald is the valuable half; amber the
 * cheaper one, which is the design system's solar/optimal semantic preserved.
 *
 * Bar widths come from band midpoints, because a stacked bar has to sum to one
 * width. The bands are printed rather than dropped — an interval cannot be
 * shown as a boundary between two blocks without implying a precision the
 * calculation does not have.
 */
export default function EnergySplitBar({ generation, selfConsumed, exported, kwpLabel }) {
  const mid = (r) => (r.lo + r.hi) / 2;
  const s = mid(selfConsumed);
  const e = mid(exported);
  const total = s + e;
  if (total <= 0) return null;
  const selfPct = (s / total) * 100;

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="caption">Predicted generation</span>
        <span className="mono text-metric-label text-ink">
          {kwh(mid(generation))} kWh / yr
          {kwpLabel && <span className="text-ink-subtle"> · {kwpLabel}</span>}
        </span>
      </div>

      <div
        className="mt-1.5 flex h-2 w-full overflow-hidden rounded-sm"
        role="img"
        aria-label={`About ${Math.round(selfPct)} percent of generation used in the home, the rest exported`}
      >
        <div className="bg-grid" style={{ width: `${selfPct}%` }} />
        <div className="bg-solar" style={{ width: `${100 - selfPct}%` }} />
      </div>

      <div className="mt-1.5 flex flex-wrap justify-between gap-2 font-mono text-code-mono">
        <span className="flex items-center gap-1.5 text-grid-deep">
          <span className="chip-dot bg-grid" aria-hidden="true" />
          {kwh(s)} kWh self-consumed
        </span>
        <span className="flex items-center gap-1.5 text-solar-deep">
          <span className="chip-dot bg-solar" aria-hidden="true" />
          {kwh(e)} kWh grid exported
        </span>
      </div>

      <div className="mt-1 flex flex-wrap justify-between gap-2">
        {selfConsumed.lo !== selfConsumed.hi && (
          <span className="band">
            {kwh(selfConsumed.lo)} to {kwh(selfConsumed.hi)}
          </span>
        )}
        {exported.lo !== exported.hi && (
          <span className="band">
            {kwh(exported.lo)} to {kwh(exported.hi)}
          </span>
        )}
      </div>
    </div>
  );
}
