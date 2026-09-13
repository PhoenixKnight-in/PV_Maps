import { useEffect } from "react";
import { Route, Routes } from "react-router-dom";
import HomePage from "./pages/HomePage";
import ResultsPage from "./pages/ResultsPage";
import ErrorBoundary from "./components/ErrorBoundary";
import { OfflineStrip } from "./components/OfflineNotice";
import { probeApi } from "./api/dataSource";

/**
 * The workstation shell, from the Bill-to-Roof Optimiser (Light) reference
 * screen: fixed 56px utility header, core-thesis micro-strip, full-bleed
 * working viewport, mandatory regulatory bar, technical footer.
 *
 * What the reference screen's chrome carries that this one does not, and why:
 *
 *   Nav: Grid Intelligence Mode, DT Capacity & Queue, Area Analytics — Phase 2
 *        views. ARCHITECTURE.md 5.2: the Phase 1 API has no transformer,
 *        quota, allocation or grid-eligibility endpoint. A tab with nothing
 *        behind it is how that boundary starts leaking.
 *   Strip: FEEDER 11kV VIT-04, DT LOAD 68% — network telemetry Phase 1 cannot
 *        obtain (PRD 2.3).
 *   Header: global search and an account control — neither exists in Phase 1,
 *        and ARCHITECTURE.md 8 says not to add authentication.
 */
export default function App() {
  // ARCHITECTURE.md 9.3 — establish which world we are in before the first
  // keystroke, so a dead API shows as a labelled offline session rather than as
  // a search box that mysteriously finds nothing.
  useEffect(() => {
    probeApi();
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-canvas text-ink">
      <header className="sticky top-0 z-40 border-b border-hairline bg-surface/95 backdrop-blur-hud">
        <div className="flex min-h-14 w-full flex-wrap items-center justify-between gap-x-4 gap-y-1.5 px-4 py-1.5 sm:px-5">
          <div className="flex shrink-0 items-center gap-3">
            <span
              className="flex h-7 w-7 items-center justify-center rounded bg-ink font-mono text-caption font-semibold text-white"
              aria-hidden="true"
            >
              PV
            </span>
            <div className="flex flex-col">
              <div className="flex items-center gap-2">
                <span className="font-mono text-caption font-semibold uppercase tracking-[0.12em] text-ink">
                  PV Maps
                </span>
                <span className="chip chip-sky">Tamil Nadu Pilot (Vellore)</span>
              </div>
              <div className="mt-0.5 flex items-center gap-1.5">
                <span className="chip-dot bg-grid" aria-hidden="true" />
                <span className="font-mono text-code-mono uppercase tracking-[0.04em] text-ink-muted">
                  Pilot area: Vellore Ward 12 active
                </span>
              </div>
            </div>
          </div>

          <nav className="flex min-w-0 items-center gap-1.5" aria-label="Views">
            {/* One view, because one view exists. The full label is dropped on
                narrow screens rather than allowed to push the bar wider than
                the viewport. */}
            <span className="flex h-7 items-center truncate rounded bg-ink px-2.5 font-sans text-code-mono font-medium text-white sm:text-body-sm">
              <span className="hidden sm:inline">Bill-to-Roof Optimiser</span>
              <span className="sm:hidden">Optimiser</span>
            </span>
            <span className="chip chip-neutral shrink-0">Phase 1</span>
          </nav>
        </div>

        {/* Core-thesis micro-strip */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-well bg-canvas px-4 py-1.5 sm:px-5">
          <span className="font-mono text-code-mono font-semibold uppercase tracking-[0.06em] text-ink-sub">
            Core thesis:
          </span>
          <p className="text-caption normal-case tracking-normal text-ink-muted">
            <span className="font-medium text-ink-sub">
              “The roof is not the recommendation. The bill is.”
            </span>{" "}
            — bill-aware daytime solar sizing constrained by contracted load and
            dated export tariffs.
          </p>
          <span className="flex min-w-0 flex-wrap items-center gap-1.5 sm:ml-auto">
            <span className="chip chip-neutral">Vellore urban pilot</span>
            <span className="chip chip-warn">Grid feasibility: not verified</span>
          </span>
        </div>

        <OfflineStrip />
      </header>

      <main className="flex-1">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/results/:runId" element={<ResultsPage />} />
          </Routes>
        </ErrorBoundary>
      </main>

      <footer className="border-t border-hairline bg-surface px-5 py-3">
        <p className="text-code-mono leading-4 text-ink-muted">
          <span className="font-mono font-semibold uppercase tracking-[0.04em] text-ink-sub">
            Disclaimer: not official TNPDCL feasibility approval.
          </span>{" "}
          PV Maps models dated TNPDCL tariff and subsidy rules and PostGIS
          cartographic estimations for the Vellore urban pilot. It does not model
          the distribution network.
        </p>
        <div className="mt-2 grid gap-1 border-t border-well pt-2 font-mono text-code-mono uppercase tracking-[0.04em] text-ink-subtle sm:grid-cols-3">
          <span>Tamil Nadu energy platform</span>
          <span className="sm:text-center">GeoJSON EPSG:4326</span>
          <span className="sm:text-right">PV Maps infrastructure · Phase 1</span>
        </div>
      </footer>
    </div>
  );
}
