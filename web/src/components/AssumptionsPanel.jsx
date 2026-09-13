import Panel from "./ui/Panel";
import Chip from "./ui/Chip";

/**
 * ARCHITECTURE.md 4.1 step 7 and 11 — every dated assumption, on screen.
 * Nothing here may be called "verified" unless the API says the rule pack was
 * checked against a primary source.
 */
export default function AssumptionsPanel({ recommendation: r }) {
  if (!r) return null;

  const rows = [
    ["Tariff rules", r.tariff_version],
    ["Subsidy rules", r.subsidy_version],
    ["Solar assumptions", r.assumptions_version],
  ];

  return (
    <Panel
      title="Calculation assumptions"
      aside={
        <Chip tone={r.yield_source === "BUILDING" ? "ok" : "warn"} dot>
          {r.yield_source === "BUILDING" ? "Roof analysis" : "Regional yield"}
        </Chip>
      }
    >
      {!r.assumptions_verified && (
        <p className="notice notice-warn mb-2">
          Provisional — one or more rule packs has not yet been checked against
          its primary source, so treat these figures as indicative.
        </p>
      )}

      <table className="telemetry">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className="text-ink-muted">{k}</td>
              <td className="num text-ink-sub">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="mt-2 border-t border-well pt-2 text-code-mono leading-4 text-ink-muted">
        {r.yield_source === "REGIONAL_FALLBACK"
          ? "Generation comes from a regional yield band, not a pvlib run for this specific roof."
          : "Generation comes from a pvlib analysis of this roof."}{" "}
        {r.usable_area_source === "USER_CORRECTED"
          ? "Using your usable-area figure instead of ours."
          : "Usable area came from roof segmentation."}
      </p>
    </Panel>
  );
}
