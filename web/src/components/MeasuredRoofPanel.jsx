import Panel from "./ui/Panel";
import Chip from "./ui/Chip";
import { Metric } from "./ui/Metric";

/**
 * A roof measured live, and the alternatives to it.
 *
 * The whole point of this panel is the second half. SAM2 returns the same point
 * at several nested scales, and its own confidence does not rank them the way a
 * person would -- on the VIT tile the outline of the entire building scored
 * 0.069 while a kiosk in its courtyard scored 0.814. So the pick shown here is
 * a heuristic (largest outline that is still roof-sized), and the alternatives
 * are given equal billing rather than hidden behind a disclosure.
 *
 * FR-1.5: the assumption has to be correctable. One tap, on the panel or on the
 * map, is the correction.
 */
export default function MeasuredRoofPanel({
  measuring,
  measured,
  chosenIndex,
  onPick,
  error,
}) {
  const layout = measured?.layout ?? null;
  if (measuring) {
    return (
      <Panel
        title="Measuring roof"
        aside={
          <Chip tone="warn" dot>
            GPU
          </Chip>
        }
      >
        <p className="text-body-sm leading-5 text-ink-muted">
          Fetching satellite imagery and segmenting the roof under the pin. This
          takes a few seconds the first time a location is used.
        </p>
        <div className="mt-2 h-1 w-full overflow-hidden rounded-sm bg-well">
          <div className="h-full w-1/3 animate-pulse rounded-sm bg-solar" />
        </div>
      </Panel>
    );
  }

  const candidates = measured?.candidates ?? [];
  const chosen = chosenIndex != null ? candidates[chosenIndex] : null;

  return (
    <Panel
      title="Measured roof"
      aside={
        <Chip tone={chosen ? "ok" : "warn"}>
          {chosen ? "Live" : "Unresolved"}
        </Chip>
      }
    >
      {error && (
        <p className="mb-2 text-code-mono leading-4 text-critical">{error}</p>
      )}

      {chosen ? (
        <Metric
          label="Detected roof area"
          value={Math.round(chosen.area_m2).toLocaleString()}
          unit="m²"
          hint="Segmented from satellite imagery. Confirm it matches the outline on the map."
        />
      ) : (
        <p className="text-body-sm leading-5 text-ink-muted">
          No roof-sized outline here. Tap the roof itself on the map, or enter
          the area by hand below.
        </p>
      )}

      {layout && (
        <div className="mt-3 border-t border-well pt-2">
          <div className="grid grid-cols-2 gap-2">
            <Metric
              label="Panels that fit"
              value={layout.panel_count.toLocaleString()}
              unit={`× ${layout.panel_watts} W`}
            />
            <Metric
              label="Array if filled"
              value={layout.array_kwp.toLocaleString()}
              unit="kWp"
            />
          </div>
          <p className="mt-1.5 text-code-mono leading-4 text-ink-muted">
            Dark rectangles on the map are the modules; the green dashed line is
            what is left after a 0.5 m parapet setback (
            {Math.round(layout.usable_area_m2)} m² of{" "}
            {Math.round(chosen?.area_m2 ?? 0)} m²). Rows are{" "}
            {layout.row_pitch_m} m apart at {layout.tilt_deg}° tilt, which is
            the spacing that keeps the back row unshaded at winter noon.
          </p>
          <p className="mt-1.5 text-code-mono leading-4 text-ink-subtle">
            This is what the roof <em>could</em> hold. Your bill decides how
            much of it is worth buying — that is the next step, and it is
            usually far less than a full roof.
          </p>
        </div>
      )}

      {candidates.length > 1 && (
        <div className="mt-3 border-t border-well pt-2">
          <p className="caption">
            {chosen ? "Not the right outline?" : "Outlines found here"}
          </p>
          <p className="mt-0.5 text-code-mono leading-4 text-ink-muted">
            The model outlines the same point at several scales. Pick the one
            that is your roof.
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {candidates.map((c, i) => (
              <button
                key={i}
                type="button"
                onClick={() => onPick(i)}
                aria-pressed={i === chosenIndex}
                className={`rounded border px-2 py-1 text-code-mono transition ${
                  i === chosenIndex
                    ? "border-solar bg-solar-tint text-ink"
                    : "border-rail bg-surface text-ink-muted hover:bg-canvas"
                }`}
              >
                {Math.round(c.area_m2).toLocaleString()} m²
                {!c.plausible && <span className="ml-1 text-critical">!</span>}
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-code-mono leading-4 text-ink-subtle">
            Marked <span className="text-critical">!</span> means outside the
            15–5,000 m² range a rooftop normally falls in.
          </p>
        </div>
      )}

      <p className="mt-3 border-t border-well pt-2 text-code-mono leading-4 text-ink-subtle">
        Measured from imagery, not surveyed. There is no roof/not-roof
        classifier behind this yet, so the outline is a proposal — check it
        against the map before trusting the area.
      </p>
    </Panel>
  );
}
