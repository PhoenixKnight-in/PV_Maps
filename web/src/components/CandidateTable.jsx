import Panel from "./ui/Panel";
import Chip from "./ui/Chip";
import { inr, kwh, kwp, years } from "./ui/format";

/**
 * Recommended size against the largest size you are allowed, line by line.
 *
 * The argument Phase 1 has to make is entirely private to the household:
 * buying up to your ceiling costs more and returns less per rupee, because the
 * extra generation lands in export rather than displacing an imported unit at
 * your marginal slab (FR-4.1).
 *
 * Every figure is read straight off `curve` — the same array the chart plots.
 * Nothing here is recomputed in the browser.
 */
const mid = (r) => (r.lo + r.hi) / 2;
const rupeePerKwh = (n) => "₹" + n.toFixed(2);

const ROWS = [
  ["System size", (c) => kwp(c.kwp) + " kWp", true],
  ["Annual generation", (c) => kwh(mid(c.annual_generation)) + " kWh"],
  ["Self-consumed", (c) => kwh(mid(c.annual_self_consumed_kwh)) + " kWh/yr"],
  ["Exported", (c) => kwh(mid(c.annual_exported_kwh)) + " kWh/yr"],
  ["Import offset", (c) => inr(mid(c.annual_bill_savings)) + "/yr"],
  ["Export credit", (c) => inr(mid(c.annual_export_credit)) + "/yr"],
  ["Net benefit", (c) => inr(mid(c.annual_net_benefit)) + "/yr", true],
  ["Cost after subsidy", (c) => inr(mid(c.net_capex))],
  ["Payback", (c) => (c.payback_years ? years(mid(c.payback_years)) + " yrs" : "never")],
  ["Realised per kWh", (c) => rupeePerKwh(mid(c.effective_rate)), true],
];

export default function CandidateTable({ recommendation: r }) {
  const rec = r.recommended;
  if (!rec || !r.is_economically_capped) return null;

  const ceiling = r.curve.reduce(
    (best, c) => (c.kwp <= r.feasible_max_kwp && (!best || c.kwp > best.kwp) ? c : best),
    null,
  );
  if (!ceiling || ceiling.kwp === rec.kwp) return null;

  return (
    <Panel
      floating
      title="Recommended vs largest allowed"
      aside={<Chip tone="neutral">From the value curve</Chip>}
      bodyClass="!p-0"
    >
      <div className="overflow-x-auto">
        <table className="telemetry">
          <thead>
            <tr>
              <th className="caption font-medium">Metric</th>
              <th className="text-right">
                <span className="caption !text-solar-deep">We recommend</span>
                <span className="mono block text-metric-label text-solar-deep">
                  {kwp(rec.kwp)} kWp
                </span>
              </th>
              <th className="text-right">
                <span className="caption">Largest allowed</span>
                <span className="mono block text-metric-label text-ink-sub">
                  {kwp(ceiling.kwp)} kWp
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map(([label, fmt, strong]) => (
              <tr key={label}>
                <td className="text-ink-muted">{label}</td>
                <td
                  className={
                    "num bg-solar-tint/60 " +
                    (strong ? "font-medium text-solar-deep" : "text-ink")
                  }
                >
                  {fmt(rec)}
                </td>
                <td className={"num " + (strong ? "font-medium text-ink-sub" : "text-ink-muted")}>
                  {fmt(ceiling)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-well px-2 py-2 text-code-mono leading-4 text-ink-muted">
        Both sizes are allowed. The larger one costs more and sends more of its
        output to export, which settles separately from the units you avoid
        buying — so each extra panel returns less than the one before it.
      </p>
    </Panel>
  );
}
