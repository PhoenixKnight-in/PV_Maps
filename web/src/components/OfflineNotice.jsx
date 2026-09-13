import { useState } from "react";
import { probeApi, useDataState } from "../api/dataSource";

/**
 * ARCHITECTURE.md 9.3 requires the app to keep working when the sizing service
 * does not. NFR "Honesty" requires it to say so: an offline result is a stored
 * scenario, not an answer to the household in front of the screen, and the
 * difference has to be visible without being asked for.
 *
 * Grid Spatial Studio's semantic colour rule puts this on the solar/amber
 * channel — a degraded but working state, not a failure. Critical red is
 * reserved for the case where even the bundle could not be read.
 */

/** Persistent header strip. Rendered under the core-thesis micro-strip. */
export function OfflineStrip() {
  const { mode, reason } = useDataState();
  const [retrying, setRetrying] = useState(false);

  if (mode !== "FALLBACK") return null;

  async function retry() {
    setRetrying(true);
    try {
      await probeApi();
    } finally {
      setRetrying(false);
    }
  }

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-solar-border bg-solar-tint px-4 py-1.5 sm:px-5"
    >
      <span className="chip chip-warn shrink-0">
        <span className="chip-dot bg-solar" aria-hidden="true" />
        Offline demo data
      </span>
      <p className="text-caption normal-case tracking-normal text-solar-deep">
        <span className="font-medium">{reason}</span> Running on the pilot roofs
        and stored sizing results bundled with the app. Nothing on screen is
        being calculated live.
      </p>
      <button
        type="button"
        onClick={retry}
        disabled={retrying}
        className="btn-secondary shrink-0 sm:ml-auto"
      >
        {retrying ? "Checking…" : "Retry connection"}
      </button>
    </div>
  );
}

/**
 * Shown above an offline result. It has one job: stop anyone reading these
 * rupee figures as an answer to the bill they just typed in.
 */
export function OfflineResultNotice({ corrected = false }) {
  return (
    <div className="px-4 pt-3">
      <div className="notice notice-warn">
        <p className="font-medium">
          Offline demo result — this is a stored pilot scenario
        </p>
        <p className="mt-1 leading-[18px]">
          The sizing service is unreachable, so the optimiser could not run. Every
          figure below was produced by that same optimiser and bundled with the
          app, but for a stored household profile attached to this roof — not for
          the bill details
          {corrected ? " or the roof correction" : ""} you entered. Treat it as a
          worked example of the calculation, not as your result.
        </p>
      </div>
    </div>
  );
}
