import Panel from "./ui/Panel";
import Chip from "./ui/Chip";

/**
 * ARCHITECTURE.md 4.1 step 5 — occupancy, daytime loads, expected new loads.
 *
 * Four buckets, not a slider. A slider would imply the household knows a number
 * it cannot know without an interval meter, and would put false precision into
 * the single widest band in the whole calculation.
 */
const OCCUPANCY = [
  ["EMPTY_WEEKDAYS", "Nobody home during working hours"],
  ["PARTIAL", "Someone home part of the day"],
  ["HOME_ALL_DAY", "Home all day (work from home, retired, joint family)"],
  ["DAYTIME_HEAVY", "Daytime AC, water pump, or shop load"],
];

const MODIFIERS = [
  ["DAYTIME_AC_PLANNED", "Planning to add daytime air conditioning"],
  ["EV_CHARGED_AT_NIGHT", "Electric vehicle, charged overnight"],
  ["EV_CHARGED_BY_DAY", "Electric vehicle, charged during the day"],
];

/** Still a real radio/checkbox underneath — the row is the label, so keyboard
 *  and screen-reader behaviour is unchanged. */
function Choice({ type, name, checked, onChange, children }) {
  return (
    <label
      className={`flex cursor-pointer items-start gap-2 rounded border px-2 py-1.5 text-body-sm leading-[18px] transition ${
        checked
          ? "border-sky bg-sky-tint text-ink"
          : "border-hairline bg-surface text-ink-sub hover:border-ink-subtle"
      }`}
    >
      <input type={type} name={name} className="mt-0.5 accent-ink" checked={checked} onChange={onChange} />
      <span>{children}</span>
    </label>
  );
}

export default function DaytimeUseForm({ value, onChange }) {
  const modifiers = value.modifiers ?? [];

  function toggle(m) {
    onChange({
      ...value,
      modifiers: modifiers.includes(m) ? modifiers.filter((x) => x !== m) : [...modifiers, m],
    });
  }

  return (
    <Panel floating title="Daytime load signature" aside={<Chip tone="warn">Widest band</Chip>}>
      <p className="text-code-mono leading-4 text-ink-muted">
        Solar only helps while the sun is up. This is the biggest single factor
        in what a system is worth to you.
      </p>

      <fieldset className="mt-2 space-y-1">
        <legend className="sr-only">Occupancy</legend>
        {OCCUPANCY.map(([k, label]) => (
          <Choice
            key={k}
            type="radio"
            name="occupancy"
            checked={value.occupancy === k}
            onChange={() => onChange({ ...value, occupancy: k })}
          >
            {label}
          </Choice>
        ))}
      </fieldset>

      <fieldset className="mt-3 space-y-1 border-t border-well pt-2">
        <legend className="metric-label mb-1.5">Anything changing soon?</legend>
        {MODIFIERS.map(([k, label]) => (
          <Choice key={k} type="checkbox" checked={modifiers.includes(k)} onChange={() => toggle(k)}>
            {label}
          </Choice>
        ))}
      </fieldset>
    </Panel>
  );
}
