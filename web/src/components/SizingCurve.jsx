import {
  Area,
  ComposedChart,
  Line,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import Panel from "./ui/Panel";
import Chip from "./ui/Chip";
import { inr, kwp } from "./ui/format";

/**
 * ARCHITECTURE.md 7f — "returns the best-value size plus the entire comparison
 * curve."
 *
 * The curve is the argument, not decoration. It is what shows that savings
 * flatten once a system outgrows the daytime load, which is why the
 * recommendation sits below the roof maximum. A single recommended number would
 * have to be taken on trust; the curve can be checked by eye.
 *
 * Markers, per the reference screen: a hard-cap vertical at the sanctioned
 * load, and a highlighted vertex at the recommendation.
 */
const SKY = "#0284c7";
const SKY_DEEP = "#0369a1";
const SOLAR = "#d97706";
const CRITICAL = "#dc2626";
const MUTED = "#64748b";
const MONO = "JetBrains Mono, Cascadia Mono, Consolas, monospace";

export default function SizingCurve({ recommendation: r, activeKwp }) {
  if (!r?.curve?.length) return null;

  const data = r.curve.map((c) => ({
    kwp: c.kwp,
    lo: Math.round(c.annual_bill_savings.lo),
    hi: Math.round(c.annual_bill_savings.hi),
    band: [Math.round(c.annual_bill_savings.lo), Math.round(c.annual_bill_savings.hi)],
  }));

  const tick = { fontSize: 10, fill: MUTED, fontFamily: MONO };
  const rec = r.recommended;

  return (
    <Panel
      floating
      title="Candidate sizing value curve"
      aside={<Chip tone="neutral">{r.curve.length} sizes evaluated</Chip>}
    >
      <p className="text-code-mono leading-4 text-ink-muted">
        The shaded band is the honest range. It is wide because we do not have
        interval-meter data for your home.
      </p>

      <div className="mt-2 h-60 overflow-hidden">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 26, right: 12, bottom: 6, left: 0 }}>
            <XAxis
              dataKey="kwp"
              tick={tick}
              stroke="#e2e8f0"
              label={{
                value: "System size (kWp)",
                position: "insideBottom",
                offset: -4,
                fontSize: 10,
                fill: MUTED,
              }}
            />
            <YAxis tick={tick} stroke="#e2e8f0" width={52} />
            <Tooltip
              formatter={(v, name) => [inr(Number(v)), name]}
              labelFormatter={(k) => kwp(k) + " kWp"}
              contentStyle={{
                borderRadius: 4,
                border: "1px solid #cbd5e1",
                fontSize: 11,
                fontFamily: MONO,
              }}
            />
            <Area dataKey="band" stroke="none" fill={SKY} fillOpacity={0.1} />
            <Line dataKey="lo" stroke={SKY_DEEP} dot={false} strokeWidth={2} name="Conservative" />
            <Line
              dataKey="hi"
              stroke={SKY}
              dot={false}
              strokeDasharray="4 3"
              strokeWidth={1.5}
              name="Optimistic"
            />

            {/* Hard cap at the sanctioned load — the reference screen's
                vertical marker. Not a network limit: it is the service
                connection's contracted ceiling. */}
            {r.feasible_max_kwp <= data[data.length - 1].kwp && (
              <ReferenceLine
                x={r.feasible_max_kwp}
                stroke={CRITICAL}
                strokeDasharray="3 3"
                label={{
                  value: "Cap " + kwp(r.feasible_max_kwp),
                  fontSize: 10,
                  position: "top",
                  dy: 12,
                  fill: CRITICAL,
                }}
              />
            )}

            {/* The recommended vertex, marked on the conservative bound —
                the number the optimiser actually chose on. */}
            {rec && (
              <ReferenceDot
                x={rec.kwp}
                y={Math.round(rec.annual_bill_savings.lo)}
                r={4}
                fill={SOLAR}
                stroke="#ffffff"
                strokeWidth={1.5}
                isFront
              />
            )}

            {r.recommended && (
              <ReferenceLine
                x={r.recommended.kwp}
                stroke={SOLAR}
                strokeWidth={2}
                label={{
                  value: "Best fit " + kwp(r.recommended.kwp),
                  fontSize: 10,
                  position: "top",
                  fill: SOLAR,
                }}
              />
            )}

            {/* Where the scrubber currently sits, when it is not on the
                recommendation. */}
            {activeKwp != null && activeKwp !== r.recommended?.kwp && (
              <ReferenceLine x={activeKwp} stroke={MUTED} strokeWidth={1} />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {r.is_economically_capped && (
        <p className="mt-2 border-t border-well pt-2 text-code-mono leading-4 text-ink-sub">
          The largest system you are allowed is{" "}
          <span className="mono text-ink">{kwp(r.feasible_max_kwp)} kWp</span>, but we recommend{" "}
          <span className="mono text-solar-deep">{kwp(r.recommended?.kwp)} kWp</span>. Beyond that,
          the extra panels mostly export, and export is worth less than the units
          you displace at home.
        </p>
      )}
    </Panel>
  );
}
