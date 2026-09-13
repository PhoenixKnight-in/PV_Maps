import { z } from "zod";

/**
 * ARCHITECTURE.md 8: "Validate all form data with matching Zod browser schemas
 * and Pydantic API schemas."
 *
 * These mirror `pvmaps/api/schemas.py` FIELD FOR FIELD. Zod strips unknown keys
 * by default, so a field missing here is not a lint problem -- it is silently
 * deleted before the UI ever sees it. That is exactly how the annual energy
 * figures PRD 5.2 requires, the API's own `grid_disclosure`, and `run_id` all
 * went missing. When the Pydantic side changes, change these in the same commit.
 */

export const Occupancy = z.enum([
  "EMPTY_WEEKDAYS",
  "PARTIAL",
  "HOME_ALL_DAY",
  "DAYTIME_HEAVY",
]);

export const UsageModifier = z.enum([
  "DAYTIME_AC_PLANNED",
  "EV_CHARGED_AT_NIGHT",
  "EV_CHARGED_BY_DAY",
]);

/**
 * A closed interval. Mirrors `pvmaps.sizing.assumptions.Range` and `RangeOut`.
 *
 * The ordering check mirrors RangeOut's `_ordered` validator. The API cannot
 * emit an inverted band, so one arriving here means something upstream is
 * wrong and should fail loudly rather than render as a backwards range.
 */
export const RangeSchema = z
  .object({ lo: z.number(), hi: z.number() })
  .refine((r) => r.lo <= r.hi, { message: "inverted range: lo > hi" });

/**
 * A number that knows how much it should be trusted.
 * Mirrors `pvmaps.estimate.Estimate`.
 */
export const EstimateSchema = z.object({
  value: z.number(),
  lo: z.number(),
  hi: z.number(),
  source: z.enum(["surveyed", "published", "user_supplied", "inferred"]),
  confidence: z.number().min(0).max(1),
  as_of: z.string().nullable().optional(),
  note: z.string().nullable().optional(),
});

/**
 * The confirmed profile. ARCHITECTURE.md 6: this, not the upload, is the
 * calculation input -- so every field here must have been visible and editable
 * before submit.
 */
export const UsageProfileSchema = z
  .object({
    building_id: z.string().min(1, "Select an address first"),

    monthly_units_kwh: z.coerce
      .number({ invalid_type_error: "Enter the units from your bill" })
      .nonnegative("Units cannot be negative")
      .max(5000, "That is higher than any domestic bill — check the figure"),

    /**
     * PRD 2.1 constraint #2 and demo beat 1. Never defaulted: the API rejects a
     * missing value rather than guessing, because guessing here fabricates the
     * exact number the product exists to surface.
     */
    sanctioned_load_kw: z.coerce
      .number({ invalid_type_error: "Enter the sanctioned load from your bill" })
      .positive("Sanctioned load must be greater than zero")
      .max(150, "That is a commercial connection, not a domestic one"),

    occupancy: Occupancy,
    modifiers: z.array(UsageModifier).default([]),
  })
  .refine(
    (v) =>
      !(
        v.modifiers.includes("EV_CHARGED_AT_NIGHT") &&
        v.modifiers.includes("EV_CHARGED_BY_DAY")
      ),
    { message: "Pick one charging pattern", path: ["modifiers"] },
  );

/** Mirrors `CandidateOut`. */
export const CandidateSchema = z.object({
  kwp: z.number(),
  annual_generation: RangeSchema,

  /**
   * PER MONTH -- the API names these without a period suffix for backwards
   * compatibility, and its docstring is the authority. The results screen
   * leads with the annual pair below (PRD 5.2 asks for yearly estimates) and
   * carries these as the secondary read.
   */
  self_consumed_kwh: RangeSchema,
  exported_kwh: RangeSchema,

  annual_self_consumed_kwh: RangeSchema,
  annual_exported_kwh: RangeSchema,

  /** FR-4.3: import offset and export credit stay separate line items. */
  annual_bill_savings: RangeSchema,
  annual_export_credit: RangeSchema,

  annual_om_cost: RangeSchema,
  annual_net_benefit: RangeSchema,

  gross_capex: RangeSchema,
  subsidy: z.number(),
  net_capex: RangeSchema,

  npv: RangeSchema,
  /** Null when the pessimistic bound never pays back. "never" is the honest
   *  answer and has to stay distinguishable from zero. */
  payback_years: RangeSchema.nullable(),
  effective_rate: RangeSchema,
});

/** Mirrors `RecommendationOut`. */
export const RecommendationSchema = z.object({
  /** Opaque and short-lived (ARCHITECTURE.md 8), so it is safe in the URL.
   *  Null when the calculation succeeded but the run could not be persisted. */
  run_id: z.string().nullable().optional(),

  verdict: z.enum(["RECOMMENDED", "MARGINAL", "NOT_ECONOMIC", "NO_CAPACITY"]),
  recommended: CandidateSchema.nullable(),
  curve: z.array(CandidateSchema),

  roof_max_kwp: z.number(),
  sanctioned_load_max_kwp: z.number(),
  feasible_max_kwp: z.number(),
  binding_constraint: z.enum(["ROOF", "SANCTIONED_LOAD", "BOTH"]),
  is_economically_capped: z.boolean(),

  usable_area_m2: z.number(),
  /** FR-1.5 -- the result says so when the household's own figure was used. */
  usable_area_source: z.enum(["SEGMENTED", "USER_CORRECTED"]),

  tariff_version: z.string(),
  assumptions_version: z.string(),
  subsidy_version: z.string(),
  /**
   * False while any rule pack is still marked
   * UNVERIFIED_AGAINST_PRIMARY_SOURCE. The results screen must show a
   * provisional banner whenever this is false -- ARCHITECTURE.md 11: no
   * component may call a figure "verified" without a source and a version.
   */
  assumptions_verified: z.boolean(),
  yield_source: z.enum(["BUILDING", "REGIONAL_FALLBACK"]),

  /**
   * Phase 1 has exactly one possible value. A literal rather than an enum, so
   * that a backend edit widening it cannot pass validation unnoticed here.
   */
  grid_feasibility: z.literal("NOT_VERIFIED"),
  /** PRD 5.2, verbatim. Rendered, never paraphrased. */
  grid_disclosure: z.string().min(1),
});

export const AddressSchema = z.object({
  id: z.string(),
  display_name: z.string(),
  building_id: z.string().nullable(),
  lat: z.number(),
  lon: z.number(),
});

/** Mirrors `BuildingOut`. */
export const BuildingSchema = z.object({
  id: z.string(),
  geojson: z.unknown(),
  obstruction_geojson: z.unknown().nullable().optional(),

  roof_area_m2: z.number(),
  usable_area_m2: z.number(),

  /** The conservative cap the calculation uses. */
  roof_max_kwp: z.number(),
  /** What might physically fit, honestly. The UI may show this; the
   *  calculation uses `roof_max_kwp`. */
  roof_max_kwp_band: RangeSchema,

  typology: z.string(),
  confidence: z.number(),
  annual_yield_kwh_per_kwp: EstimateSchema,
  yield_source: z.enum(["BUILDING", "REGIONAL_FALLBACK"]),
  analysis_version: z.string().nullable().optional(),
});

export type UsageProfileInput = z.input<typeof UsageProfileSchema>;
export type UsageProfile = z.output<typeof UsageProfileSchema>;
export type Recommendation = z.infer<typeof RecommendationSchema>;
export type Candidate = z.infer<typeof CandidateSchema>;
export type Address = z.infer<typeof AddressSchema>;
export type Building = z.infer<typeof BuildingSchema>;
export type Estimate = z.infer<typeof EstimateSchema>;
export type Range = z.infer<typeof RangeSchema>;
