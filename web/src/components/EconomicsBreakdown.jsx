import Panel from "./ui/Panel";
import Chip from "./ui/Chip";
import { BandedMetric, Metric } from "./ui/Metric";
import { inr, kwh, kwp, years } from "./ui/format";

/**
 * The economics ledger — PRD 5.2's required outputs, all annual.
 *
 * FR-4.3 is why import offset and export credit are two line items and never
 * one "savings" number. FR-4.1 is why neither is generation times an average
 * tariff. The API also carries monthly self-use and export
 * (`self_consumed_kwh` / `exported_kwh`), kept here as the secondary read
 * because the bill in the household's hand is bimonthly.
 */
export default function EconomicsBreakdown({ recommendation: r }) {
  if (!r) return null;
  const c = r.recommended;

  if (r.verdict === "NOT_ECONOMIC") {
    return (
      <Panel title="Economics" aside={<Chip tone="critical">Not economic</Chip>}>
        <p className="notice notice-neutral">
          <span className="font-medium text-ink">
            On your current bill, solar would save you almost nothing.
          </span>{" "}
          Your consumption sits inside the free and low-priced slabs, so there is
          little for solar to displace. That can change: if your usage rises, or
          you add daytime load, come back and run this again. We are not going to
          sell you a system that does not pay for itself.
        </p>
      </Panel>
    );
  }

  if (!c) return null;

  const rupeePerKwh = (n) => "₹" + n.toFixed(2);

  return (
    <Panel
      title="Economics ledger"
      aside={
        <Chip tone={r.verdict === "MARGINAL" ? "warn" : "ok"} dot>
          {r.verdict === "MARGINAL" ? "Marginal" : "Recommended"} · {kwp(c.kwp)} kWp
        </Chip>
      }
      bodyClass="!p-0"
    >
      {r.verdict === "MARGINAL" && (
        <p className="notice notice-warn m-3 mb-0">
          <span className="font-medium">This one is genuinely borderline.</span> It
          pays back only if the optimistic assumptions hold. Read the assumptions
          before deciding.
        </p>
      )}

      <dl className="cell-grid grid-cols-2 !rounded-none !border-0 !border-b sm:grid-cols-4">
        <BandedMetric
          className="cell"
          label="Annual generation"
          range={c.annual_generation}
          format={kwh}
          unit="kWh/yr"
          tone="solar"
        />
        <BandedMetric
          className="cell"
          label="Import offset"
          range={c.annual_bill_savings}
          unit="/yr"
          tone="grid"
          hint="Units you stop buying, at your marginal slab."
        />
        <BandedMetric
          className="cell"
          label="Export credit"
          range={c.annual_export_credit}
          unit="/yr"
          tone="solar"
          hint="Settled separately from your import tariff."
        />
        <BandedMetric
          className="cell"
          label="Net benefit"
          range={c.annual_net_benefit}
          unit="/yr"
          hint="Offset plus credit, less maintenance."
        />
      </dl>

      <dl className="cell-grid grid-cols-2 !rounded-none !border-0 !border-b sm:grid-cols-4">
        <BandedMetric className="cell" label="Cost after subsidy" range={c.net_capex} size="sm" />
        <BandedMetric className="cell" label="Before subsidy" range={c.gross_capex} size="sm" />
        <Metric className="cell" label="Subsidy applied" value={inr(c.subsidy)} size="sm" />
        <BandedMetric
          className="cell"
          label="Payback"
          range={c.payback_years ?? { lo: 0, hi: 0 }}
          format={(n) => (c.payback_years ? years(n) : "never")}
          unit={c.payback_years ? "yrs" : ""}
          size="sm"
        />
      </dl>

      <dl className="cell-grid grid-cols-2 !rounded-none !border-0 sm:grid-cols-4">
        <BandedMetric
          className="cell"
          label="Self-consumed"
          range={c.annual_self_consumed_kwh}
          format={kwh}
          unit="kWh/yr"
          size="sm"
          tone="grid"
        />
        <BandedMetric
          className="cell"
          label="Exported"
          range={c.annual_exported_kwh}
          format={kwh}
          unit="kWh/yr"
          size="sm"
          tone="solar"
        />
        <BandedMetric
          className="cell"
          label="Maintenance"
          range={c.annual_om_cost}
          unit="/yr"
          size="sm"
        />
        <BandedMetric
          className="cell"
          label="Realised per kWh"
          range={c.effective_rate}
          format={rupeePerKwh}
          unit="/kWh"
          size="sm"
          hint="Falls as the system outgrows your daytime load."
        />
      </dl>

      <p className="border-t border-well px-3 py-2 text-code-mono leading-4 text-ink-muted">
        Per month, about{" "}
        <span className="mono text-ink-sub">
          {kwh((c.self_consumed_kwh.lo + c.self_consumed_kwh.hi) / 2)} kWh
        </span>{" "}
        used at home and{" "}
        <span className="mono text-ink-sub">
          {kwh((c.exported_kwh.lo + c.exported_kwh.hi) / 2)} kWh
        </span>{" "}
        exported.
        {c.exported_kwh.hi > 0 && c.annual_export_credit.hi === 0 && (
          <>
            {" "}
            Exported units are counted as worth nothing here: Tamil Nadu pays a
            separate net-metering rate for export and we have not verified it for
            this tariff period, so we leave it out rather than guess high.
          </>
        )}
      </p>
    </Panel>
  );
}
