/**
 * Number formatting, in one place.
 *
 * The design system's rule for numerals: tabular lining figures, and every
 * value bound to an explicit engineering unit. The unit is rendered as a
 * separate muted span by the Metric components rather than glued into the
 * string, so a column of values still aligns on the digits.
 */

export const inr = (n) => `₹${Math.round(n).toLocaleString("en-IN")}`;

export const kwh = (n) => Math.round(n).toLocaleString("en-IN");

/**
 * kWp as the API gave it, shown to at least one decimal.
 *
 * Never re-rounded upward: `roof_max_kwp` is a conservative cap computed with
 * ROUND_DOWN server-side, and rounding it up here would undo that on the most
 * load-bearing number on the screen. `maximumFractionDigits: 2` keeps a 0.16
 * kWp ceiling legible rather than flattening it to 0.2.
 */
export const kwp = (n) =>
  Number(n).toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 2 });

export const years = (n) => Number(n).toFixed(1);

export const area = (n) => Math.round(n).toLocaleString("en-IN");
