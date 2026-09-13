/**
 * The workstation shell both Phase 1 screens are built on.
 *
 * The design system's layout model: a fluid spatial canvas with analytical
 * panels docked over it, hairlines rather than shadows, and a single reflow
 * rule — below the dual-dock breakpoint the canvas becomes an inline band and
 * the rails become the document flow, so a phone gets the same sequence rather
 * than a squeezed copy of the desktop grid.
 *
 * The canvas renders only from `xl` up, where there is room for panels to float
 * over it without covering the thing they describe. Everything still renders
 * with no canvas at all, which ARCHITECTURE.md 10 item 5 requires of the result
 * screen.
 */

/** Blueprint ground for the canvas before a parcel is loaded. Drawn in CSS —
 *  ARCHITECTURE.md 9.3 wants no external asset on stage. */
const GRID = {
  backgroundImage:
    "linear-gradient(to right, rgba(148,163,184,0.16) 1px, transparent 1px)," +
    "linear-gradient(to bottom, rgba(148,163,184,0.16) 1px, transparent 1px)," +
    "linear-gradient(to right, rgba(148,163,184,0.28) 1px, transparent 1px)," +
    "linear-gradient(to bottom, rgba(148,163,184,0.28) 1px, transparent 1px)",
  backgroundSize: "16px 16px, 16px 16px, 96px 96px, 96px 96px",
};

export default function Workstation({ canvas, inlineCanvas, emptyLabel, left, right, children }) {
  return (
    <div className="relative xl:min-h-[720px]">
      <div className="absolute inset-0 hidden bg-well xl:block" aria-hidden="true">
        {canvas ?? (
          <div className="relative h-full w-full" style={GRID}>
            {emptyLabel && (
              <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-center">
                <p className="metric-label">{emptyLabel}</p>
                <p className="mono mt-1 text-code-mono text-ink-subtle">
                  EPSG:4326 · Vellore urban pilot
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="relative z-10 grid gap-3 p-4 xl:grid-cols-[minmax(0,360px)_minmax(0,420px)] xl:justify-between">
        {/* Below xl the canvas sits in flow, first, so the roof is still the
            first thing a phone user sees. */}
        {inlineCanvas && <div className="xl:hidden">{inlineCanvas}</div>}

        <div className="space-y-3">{left}</div>
        <div className="space-y-3">{right}</div>
      </div>

      {children}
    </div>
  );
}
