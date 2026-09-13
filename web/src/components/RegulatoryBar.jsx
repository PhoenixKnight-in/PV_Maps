/**
 * The mandatory utility & feasibility regulatory bar.
 *
 * PRD 5.2 requires this exact sentence on every Phase 1 result. It is not
 * paraphrased, not summarised, and not conditional on the verdict.
 *
 * The string renders from the API payload, where `RecommendationOut` carries it
 * as `grid_disclosure` so any consumer of the API — an installer's own tooling,
 * a CSV export — receives a recommendation and its disclosure together. The
 * constant is the fallback for a screen rendered without a recommendation.
 *
 * The reference bar ends with a "VIEW DT PRESSURE (VIT-04 FEEDER)" action.
 * That is a Phase 2 destination over data Phase 1 cannot obtain (PRD 2.3), so
 * the bar states the limit and stops there.
 */
export const REQUIRED_DISCLOSURE =
  "Grid connection is not verified. Official TNPDCL feasibility is required before installation.";

export default function RegulatoryBar({ recommendation }) {
  const text = recommendation?.grid_disclosure?.trim() || REQUIRED_DISCLOSURE;

  return (
    <aside
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-solar-border bg-solar-tint px-5 py-2"
      aria-label="Regulatory notice"
    >
      <span className="font-mono text-code-mono font-semibold uppercase tracking-[0.06em] text-solar-deep">
        Regulatory notice:
      </span>
      <p className="text-body-sm font-medium text-solar-deep">{text}</p>
      <span className="ml-auto font-mono text-code-mono uppercase tracking-[0.04em] text-solar">
        Phase 1 · Bill-to-Roof Optimiser
      </span>
    </aside>
  );
}
