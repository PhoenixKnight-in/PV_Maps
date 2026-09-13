/**
 * Reconstructed from dist/assets/index-CgddShM4.css (the 2026-09-13 00:01
 * build) after this file was overwritten. Values are the compiled output's
 * own, so they are exact rather than re-derived.
 *
 * The palette is the light Spatial Intelligence system: a white/slate
 * substrate with three functional accents. Semantic names, not hues — a
 * component asks for `ink-muted`, never `slate-500`, so a palette change is
 * one edit here.
 */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Substrate
        canvas: "#f8fafc",
        surface: "#ffffff",
        well: "#f1f5f9",
        hairline: "#e2e8f0",
        rail: "#cbd5e1",

        // Type
        ink: "#0f172a",
        "ink-sub": "#334155",
        "ink-muted": "#64748b",
        "ink-subtle": "#94a3b8",

        // Functional accents. Solar = photovoltaic yield, grid = verified /
        // positive economics, critical = a hard ceiling breached.
        solar: "#d97706",
        "solar-deep": "#b45309",
        "solar-tint": "#fffbeb",
        "solar-border": "#fde68a",
        grid: "#059669",
        "grid-deep": "#065f46",
        critical: "#dc2626",

        // `sky` keeps its scale (chip-sky uses 50/200/800), gains a DEFAULT so
        // bare `border-sky` resolves, plus the two semantic steps the band and
        // notice classes use.
        sky: {
          DEFAULT: "#0284c7",
          tint: "#f0f9ff",
          deep: "#0369a1",
          50: "#f0f9ff",
          100: "#e0f2fe",
          200: "#bae6fd",
          300: "#7dd3fc",
          400: "#38bdf8",
          500: "#0ea5e9",
          600: "#0284c7",
          700: "#0369a1",
          800: "#075985",
          900: "#0c4a6e",
        },
      },

      fontFamily: {
        sans: ["Inter", "Segoe UI Variable Text", "Segoe UI", "system-ui", "-apple-system", "sans-serif"],
        display: ["Geist", "Segoe UI Variable Display", "Segoe UI", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "Cascadia Mono", "Consolas", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },

      fontSize: {
        "body-sm": ["13px", { lineHeight: "18px" }],
        caption: ["11px", { lineHeight: "14px", letterSpacing: ".02em", fontWeight: "500" }],
        "code-mono": ["11px", { lineHeight: "16px" }],
        "metric-headline": ["20px", { lineHeight: "24px", letterSpacing: "-.02em", fontWeight: "600" }],
        "metric-label": ["12px", { lineHeight: "16px", letterSpacing: ".02em", fontWeight: "500" }],
      },

      backdropBlur: { hud: "8px" },

      boxShadow: {
        hud: "0 1px 3px rgba(15, 23, 42, .05), 0 4px 12px rgba(15, 23, 42, .04)",
      },
    },
  },
  plugins: [],
};
