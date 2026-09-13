import Chip from "./Chip";
import { area, inr, kwp, years } from "./format";

/**
 * The capacity comparison — PRD FR-5's required distinction, led by the answer.
 *
 *   1. Bill-aware recommendation   what the bill can use economically
 *   2. Physical roof ceiling       what physically fits
 *   3. Sanctioned-load ceiling     what the service connection permits
 *   4. Binding constraint          which of the two actually bit
 *
 * The reference screen builds A → B → C to stage the reveal; here the
 * recommendation leads and the two ceilings sit beneath it as the evidence for
 * why it is what it is.
 *
 * Two chips from the reference are deliberately absent. "TNERC COMPLIANT" is a
 * regulatory claim this product cannot make — the tariff pack is still marked
 * UNVERIFIED_AGAINST_PRIMARY_SOURCE. "Zero grid export curtailment penalty" is
 * a statement about the network, and Phase 1 has no network data (PRD 2.3).
 */
export default function CapacityTriCard({ recommendation: r }) {
  const c = r.recommended;

  const bindingCopy = {
    SANCTIONED_LOAD: "Your sanctioned load is the limit, not your roof.",
    ROOF: "Your roof is the limit.",
    BOTH: "Your roof and your sanctioned load cap you at the same size.",
  }[r.binding_constraint];

  const roofBinds = r.binding_constraint !== "SANCTIONED_LOAD";
  const loadBinds = r.binding_constraint !== "ROOF";

  return (
    <div className="space-y-1.5">
      {/* 1 — the recommendation */}
      <div className="relative rounded border border-solar bg-solar-tint p-2.5 pt-3.5">
        <span className="absolute -top-2 left-2.5">
          <Chip tone="warn" className="!border-solar !bg-solar !text-white">
            Optimal economic fit
          </Chip>
        </span>

        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="caption !text-solar-deep">PV Maps bill-sized fit</p>
            <p className="metric-row mt-1">
              <span className="metric-lg !text-solar-deep">{c ? kwp(c.kwp) : "—"}</span>
              {c && <span className="unit !text-solar">kWp</span>}
            </p>
          </div>

          {c && (
            <div className="text-right">
              <p className="caption !text-solar-deep">Est. annual return</p>
              <p className="mono mt-1 text-metric-headline text-solar-deep">
                {inr((c.annual_net_benefit.lo + c.annual_net_benefit.hi) / 2)}
              </p>
              <p className="mono mt-0.5 text-code-mono text-solar">
                {inr(c.annual_net_benefit.lo)} to {inr(c.annual_net_benefit.hi)}
              </p>
            </div>
          )}
        </div>

        {c && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-solar-border pt-2">
            <Chip tone="ok" dot>
              {c.payback_years
                ? `${years((c.payback_years.lo + c.payback_years.hi) / 2)} yrs payback`
                : "No payback"}
            </Chip>
            <Chip tone="neutral">
              {"₹"}
              {((c.effective_rate.lo + c.effective_rate.hi) / 2).toFixed(2)}/kWh realised
            </Chip>
            {r.is_economically_capped && <Chip tone="neutral">Below your ceiling</Chip>}
          </div>
        )}
      </div>

      {/* 2 + 3 — the two ceilings that produced it */}
      <dl className="cell-grid grid-cols-2">
        <div className={`cell ${roofBinds ? "bg-canvas" : ""}`}>
          <dt className="flex items-center justify-between gap-1">
            <span className="caption">Physical roof ceiling</span>
            {roofBinds && <Chip tone="critical">Binds</Chip>}
          </dt>
          <dd className="metric-row mt-1">
            <span className="metric">{kwp(r.roof_max_kwp)}</span>
            <span className="unit">kWp</span>
          </dd>
          <dd className="mono mt-0.5 text-code-mono text-ink-subtle">
            {area(r.usable_area_m2)} m² usable
          </dd>
        </div>

        <div className={`cell ${loadBinds ? "bg-canvas" : ""}`}>
          <dt className="flex items-center justify-between gap-1">
            <span className="caption">Sanctioned-load ceiling</span>
            {loadBinds && <Chip tone="critical">Binds</Chip>}
          </dt>
          <dd className="metric-row mt-1">
            <span className="metric">{kwp(r.sanctioned_load_max_kwp)}</span>
            <span className="unit">kW</span>
          </dd>
          <dd className="mono mt-0.5 text-code-mono text-ink-subtle">Contracted service limit</dd>
        </div>
      </dl>

      {/* 4 — the binding constraint, in words */}
      <p className="rounded border border-hairline bg-canvas px-2.5 py-1.5 text-body-sm text-ink-sub">
        {bindingCopy}
      </p>
    </div>
  );
}
