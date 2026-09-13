import {
  AddressSchema,
  BuildingSchema,
  RecommendationSchema,
  type Address,
  type Building,
  type Recommendation,
  type UsageProfile,
} from "../schemas/sizing";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  parse: (raw: unknown) => T,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });

  if (!res.ok) {
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      detail = await res.text().catch(() => undefined);
    }
    throw new ApiError(`${init?.method ?? "GET"} ${path} failed`, res.status, detail);
  }

  // Parse, do not trust. A schema drift between Pydantic and Zod should fail
  // loudly here rather than render as a blank panel.
  return parse(await res.json());
}

/**
 * Every call takes an optional abort signal. A refused connection rejects
 * immediately, but a partitioned network does not: without a budget the browser
 * sits on a dead socket for half a minute, which on stage is indistinguishable
 * from a hung app. `dataSource` supplies one so an outage becomes a visible
 * fallback in seconds rather than a spinner.
 */
export interface CallOptions {
  signal?: AbortSignal;
}

export const api = {
  /** Pilot-address search. Resolves against our own table, not a live geocoder. */
  searchAddresses: (q: string, opts?: CallOptions) =>
    request(
      `/v1/search?q=${encodeURIComponent(q)}`,
      (raw) => AddressSchema.array().parse(raw),
      opts,
    ),

  getBuilding: (id: string, opts?: CallOptions) =>
    request(
      `/v1/buildings/${encodeURIComponent(id)}`,
      (raw) => BuildingSchema.parse(raw),
      opts,
    ),

  /** The confirmed profile is the calculation input. ARCHITECTURE.md 6. */
  createSizingRun: (profile: UsageProfile, opts?: CallOptions) =>
    request(
      "/v1/sizing-runs",
      (raw) => RecommendationSchema.parse(raw),
      { method: "POST", body: JSON.stringify(profile), ...opts },
    ),

  /**
   * Optional convenience only (ARCHITECTURE.md 4.3). Returns values to be
   * placed in EDITABLE fields for the user to confirm -- never fed straight
   * into a sizing run. The upload is discarded server-side after extraction.
   */
  extractBill: async (file: File): Promise<Partial<UsageProfile>> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/v1/bill-extract`, { method: "POST", body: form });
    if (!res.ok) {
      throw new ApiError("Bill extraction failed", res.status);
    }
    return res.json();
  },
};

/**
 * ARCHITECTURE.md 9.3 — demo fallback.
 *
 * If the API is unreachable, the app still demonstrates the full Bill-to-Roof
 * calculation from bundled pilot data. This is the difference between a failed
 * demo and a slower one.
 */
export async function loadDemoFallback(): Promise<{
  addresses: Address[];
  buildings: Record<string, Building>;
  recommendations: Record<string, Recommendation>;
}> {
  const res = await fetch("/demo-fallback/pilot-addresses.json");
  if (!res.ok) throw new Error("demo fallback bundle missing");
  return res.json();
}

export async function isApiReachable(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/healthz`, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}
