/**
 * Semantic telemetry chip — 20px high, 4px radius, mono 11px/500, optional
 * leading status dot. The design system reserves colour as a semantic variable,
 * so tone is chosen by meaning, never for decoration.
 */
const TONES = {
  neutral: "chip-neutral",
  sky: "chip-sky",
  ok: "chip-ok",
  warn: "chip-warn",
  critical: "chip-critical",
};

const DOTS = {
  neutral: "bg-ink-subtle",
  sky: "bg-sky",
  ok: "bg-grid",
  warn: "bg-solar",
  critical: "bg-critical",
};

export default function Chip({ tone = "neutral", dot = false, children, className = "" }) {
  return (
    <span className={`chip ${TONES[tone]} ${className}`}>
      {dot && <span className={`chip-dot ${DOTS[tone]}`} aria-hidden="true" />}
      {children}
    </span>
  );
}
