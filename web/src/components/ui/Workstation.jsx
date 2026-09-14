import { useEffect, useState } from "react";

/**
 * The workstation shell both Phase 1 screens are built on.
 *
 * Layout model: a spatial canvas with analytical rails beside it, hairlines
 * rather than shadows, and a single reflow rule — below the dual-dock breakpoint
 * the canvas becomes an inline band and the rails become the document flow, so a
 * phone gets the same sequence rather than a squeezed copy of the desktop grid.
 *
 * **The canvas is a COLUMN, not a backdrop.** It used to be
 * `absolute inset-0` with the two rails floating over it and a gap down the
 * middle, which is why the desktop view read as panels hovering in space while
 * the narrow view — where the map sits in flow — looked deliberate. Cards
 * floating over a live satellite image also put text on whatever happened to be
 * underneath, so contrast changed as the user panned.
 *
 * Now all three are real grid columns and the map scrolls with its rails,
 * sticky so it stays visible while a long right rail scrolls past it.
 * Everything still renders with no canvas at all, which ARCHITECTURE.md 10
 * item 5 requires of the result screen.
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

/**
 * True at the dual-dock breakpoint. Drives WHICH map is mounted, not which is
 * visible.
 *
 * Rendering both and hiding one with `xl:hidden` mounted two MapLibre
 * instances: two WebGL contexts, two sets of tile requests against a live
 * external tile service, and — observed 2026-09-14 — a visible map that painted
 * nothing while the hidden one happily fetched its eight tiles. Tailwind can
 * hide a DOM node; it cannot un-mount a WebGL canvas.
 */
function useIsWide(query = "(min-width: 1280px)") {
  const [wide, setWide] = useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches,
  );
  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia(query);
    const on = (e) => setWide(e.matches);
    mq.addEventListener("change", on);
    setWide(mq.matches);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return wide;
}

export default function Workstation({
  canvas,
  inlineCanvas,
  emptyLabel,
  left,
  right,
  children,
}) {
  const wide = useIsWide();

  return (
    <div className="relative">
      <div
        className={
          "grid gap-3 p-4 " +
          // Rails are fixed and readable; the canvas takes the slack, so a wide
          // monitor grows the map rather than stretching a 420px column of text.
          "xl:grid-cols-[minmax(0,360px)_minmax(0,1fr)_minmax(0,420px)] xl:items-start"
        }
      >
        {/* Below xl the canvas sits in flow, first, so the roof is still the
            first thing a phone user sees. */}
        {!wide && inlineCanvas && <div>{inlineCanvas}</div>}

        <div className="space-y-3 xl:order-1">{left}</div>

        {/* Sticky so the roof stays on screen while the right rail — which is
            much taller on the result screen — scrolls past it. */}
        {wide && (
          <div className="xl:order-2 xl:sticky xl:top-4">
            <div className="h-[calc(100vh-8rem)] min-h-[520px] overflow-hidden rounded-lg border border-hairline bg-well">
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
          </div>
        )}

        <div className="space-y-3 xl:order-3">{right}</div>
      </div>

      {children}
    </div>
  );
}
