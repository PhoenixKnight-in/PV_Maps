import { useState } from "react";
import { dataSource, useDataState } from "../api/dataSource";
import Panel from "./ui/Panel";
import Chip from "./ui/Chip";

/**
 * ARCHITECTURE.md 4.3 — manual entry is ALWAYS available; extraction is
 * convenience, not product logic.
 *
 * Extracted values land in these same editable fields and must be confirmed by
 * the user before any sizing run. The upload itself is discarded server-side.
 *
 * The reference screen badges this panel "OCR CONFIRMED: 98%". Our extractor
 * reports which field NAMES it matched plus free-text warnings — it does not
 * score its own confidence, and inventing a percentage next to a household's
 * bill figure is the precise failure FR-3.4 exists to prevent. The badge here
 * says where a value came from and leaves the checking to the user.
 *
 * It also shows a consumer service number. We never collect one: NFR "Privacy"
 * and ARCHITECTURE.md 8 keep consumer identifiers out of this system entirely.
 */
export function calculateUnitsFromAmount(b, category = "DOMESTIC") {
  const cat = (category || "DOMESTIC").toUpperCase();
  const numB = parseFloat(b) || 0;

  if (cat.includes("COMMERCIAL") || cat.includes("LT3")) {
    if (numB <= 665) return Math.round(numB / 6.65);
    return Math.round(numB / 10.45);
  }

  // DOMESTIC (LT 1A)
  if (numB <= 0) return 100;
  if (numB <= 235) return Math.round(100 + numB / 2.35);
  if (numB <= 1175) return Math.round(200 + (numB - 235) / 4.70);
  if (numB <= 1805) return Math.round(400 + (numB - 1175) / 6.30);
  if (numB <= 2645) return Math.round(500 + (numB - 1805) / 8.40);
  if (numB <= 4535) return Math.round(600 + (numB - 2645) / 9.45);
  if (numB <= 6635) return Math.round(800 + (numB - 4535) / 10.50);
  return Math.round(1000 + (numB - 6635) / 11.55);
}

export default function BillInputForm({
  value,
  onChange,
  errors,
  onLocateAddress,
  locationResolution,
  onConfirmLocation,
  onRequestUserGps,
}) {
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState(null);
  const [extracted, setExtracted] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [billAmount, setBillAmount] = useState(value.bill_amount ?? "");
  const [tariffCategory, setTariffCategory] = useState("DOMESTIC");
  const { mode } = useDataState();

  function onAmountChange(amt) {
    setBillAmount(amt);
    if (!amt || isNaN(amt)) return;
    const bimonthly = calculateUnitsFromAmount(amt, tariffCategory);
    const monthly = Math.round(bimonthly / 2);
    onChange({
      ...value,
      bill_amount: amt,
      billed_units_kwh: bimonthly,
      monthly_units_kwh: monthly,
    });
  }

  function onCategoryChange(cat) {
    setTariffCategory(cat);
    const amt = value.bill_amount ?? billAmount;
    if (amt && !isNaN(amt)) {
      const bimonthly = calculateUnitsFromAmount(amt, cat);
      const monthly = Math.round(bimonthly / 2);
      onChange({
        ...value,
        billed_units_kwh: bimonthly,
        monthly_units_kwh: monthly,
      });
    }
  }

  // FR-3.2 — "Offer manual input when upload or extraction is unavailable."
  // Extraction is server-side OCR; offline there is nothing to read the bill
  // with, and the honest move is to say so rather than to offer a control that
  // is guaranteed to fail. The two fields above stay exactly as they were.
  const canExtract = mode !== "FALLBACK";

  async function handleFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setExtracting(true);
    setExtractError(null);
    try {
      const patch = await dataSource.extractBill(file);
      onChange({ ...value, ...patch });
      setExtracted(patch.extracted_fields ?? []);
      setWarnings(patch.warnings ?? []);
      if (onLocateAddress) {
        onLocateAddress(patch);
      }
    } catch {
      // Extraction failing must never block the calculation.
      setExtractError("Could not read that bill — please type the values in.");
    } finally {
      setExtracting(false);
      e.target.value = "";
    }
  }

  return (
    <Panel
      floating
      title="Bill intelligence"
      aside={
        extracted.length > 0 ? (
          <Chip tone="warn">From bill · check</Chip>
        ) : (
          <Chip tone="neutral">Confirmed input</Chip>
        )
      }
    >
      <div className="space-y-3">
        <div>
          <div className="flex items-center justify-between gap-2">
            <label htmlFor="units" className="caption">
              Units consumed per month (kWh)
            </label>
            {extracted.includes("monthly_units_kwh") && <Chip tone="warn">From bill</Chip>}
          </div>
          <input
            id="units"
            type="number"
            inputMode="numeric"
            className="field mt-1"
            value={value.monthly_units_kwh ?? ""}
            onChange={(e) => onChange({ ...value, monthly_units_kwh: e.target.value })}
          />
          <p className="mt-1 text-code-mono leading-4 text-ink-muted">
            TN bills are usually bimonthly — enter the monthly equivalent.
          </p>
          {errors?.monthly_units_kwh && (
            <p className="mt-1 text-code-mono text-critical">
              {errors.monthly_units_kwh.message ?? errors.monthly_units_kwh}
            </p>
          )}
        </div>

        <div>
          <div className="flex items-center justify-between gap-2">
            <label htmlFor="sl" className="caption">
              Sanctioned load (kW)
            </label>
            {extracted.includes("sanctioned_load_kw") && <Chip tone="warn">From bill</Chip>}
          </div>
          <input
            id="sl"
            type="number"
            step="0.5"
            inputMode="decimal"
            className="field mt-1"
            value={value.sanctioned_load_kw ?? ""}
            onChange={(e) => onChange({ ...value, sanctioned_load_kw: e.target.value })}
          />
          <p className="mt-1 text-code-mono leading-4 text-ink-muted">
            Printed on your bill. A hard cap on system size, and usually the real
            limit rather than your roof.
          </p>
          {errors?.sanctioned_load_kw && (
            <p className="mt-1 text-code-mono text-critical">
              {errors.sanctioned_load_kw.message ?? errors.sanctioned_load_kw}
            </p>
          )}
        </div>

        {/* Bill Amount to Units Calculator */}
        <div className="rounded border border-sky-500/30 bg-sky-50/50 dark:bg-sky-950/20 p-2.5 space-y-2">
          <div className="flex items-center justify-between">
            <span className="caption font-semibold text-sky-900 dark:text-sky-300 flex items-center gap-1.5">
              💰 Calculate from Bill Amount (₹)
            </span>
            <div className="flex items-center gap-1 text-[11px]">
              <button
                type="button"
                onClick={() => onCategoryChange("DOMESTIC")}
                className={`px-2 py-0.5 rounded font-medium transition ${
                  tariffCategory === "DOMESTIC"
                    ? "bg-sky-600 text-white"
                    : "bg-ink/5 text-ink-muted hover:bg-ink/10"
                }`}
              >
                Domestic
              </button>
              <button
                type="button"
                onClick={() => onCategoryChange("COMMERCIAL")}
                className={`px-2 py-0.5 rounded font-medium transition ${
                  tariffCategory === "COMMERCIAL"
                    ? "bg-sky-600 text-white"
                    : "bg-ink/5 text-ink-muted hover:bg-ink/10"
                }`}
              >
                Commercial
              </button>
            </div>
          </div>

          <div className="flex gap-2 items-center">
            <div className="relative flex-1">
              <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-muted text-xs font-bold">
                ₹
              </span>
              <input
                type="number"
                placeholder="e.g. 2620"
                className="field pl-6 text-sm py-1 w-full font-mono"
                value={value.bill_amount ?? billAmount}
                onChange={(e) => onAmountChange(e.target.value)}
              />
            </div>
            {value.billed_units_kwh && (
              <div className="text-right shrink-0">
                <span className="text-[11px] text-ink-sub block font-mono">
                  {value.billed_units_kwh} units bi-monthly
                </span>
                <span className="text-xs font-bold text-sky-700 dark:text-sky-300 block font-mono">
                  → {value.monthly_units_kwh} kWh / mo
                </span>
              </div>
            )}
          </div>
          <p className="text-[11px] text-ink-muted leading-tight">
            Computes consumption directly from amount paid using TNERC slab tariff.
          </p>
        </div>

        {/* Meter Consumption Breakdown */}
        {value.final_reading != null && value.initial_reading != null && (
          <div className="rounded border border-emerald-500/30 bg-emerald-50/50 dark:bg-emerald-950/20 p-2.5 space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="caption font-semibold text-emerald-900 dark:text-emerald-300 flex items-center gap-1.5">
                📟 Meter Consumption Verified
              </span>
              <span className="text-[11px] font-bold px-1.5 py-0.5 rounded bg-emerald-200 dark:bg-emerald-800 text-emerald-900 dark:text-emerald-100">
                Meter #{value.meter_number || "—"}
              </span>
            </div>
            <div className="grid grid-cols-3 gap-1.5 text-xs font-mono">
              <div className="bg-white/60 dark:bg-neutral-900/60 p-1.5 rounded border border-emerald-500/20">
                <span className="text-[10px] text-ink-muted block">Final</span>
                <span className="font-bold">{value.final_reading}</span>
              </div>
              <div className="bg-white/60 dark:bg-neutral-900/60 p-1.5 rounded border border-emerald-500/20">
                <span className="text-[10px] text-ink-muted block">Initial</span>
                <span className="font-bold">{value.initial_reading}</span>
              </div>
              <div className="bg-white/60 dark:bg-neutral-900/60 p-1.5 rounded border border-emerald-500/20">
                <span className="text-[10px] text-ink-muted block">MF × Delta</span>
                <span className="font-bold text-emerald-700 dark:text-emerald-300">
                  {value.meter_consumption ?? value.billed_units_kwh} units
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Financial breakdown */}
        {value.energy_charges != null && (
          <div className="flex items-center justify-between text-[11px] font-mono px-2 py-1 rounded bg-ink/5 text-ink-sub">
            <span>Energy: ₹{value.energy_charges}</span>
            {value.government_subsidy != null && (
              <span className="text-emerald-600 dark:text-emerald-400">
                Subsidy: -₹{value.government_subsidy}
              </span>
            )}
            <span className="font-bold text-ink">Net: ₹{value.net_payable || value.bill_amount}</span>
          </div>
        )}

        {/* 4-Level Location Resolution & Verification Card */}
        {locationResolution && (
          <div
            className={`rounded border p-2.5 space-y-2 ${
              locationResolution.level === 1 || locationResolution.level === 2
                ? "border-emerald-500/40 bg-emerald-50/40 dark:bg-emerald-950/20"
                : locationResolution.requires_user_confirmation
                ? "border-amber-500/40 bg-amber-50/40 dark:bg-amber-950/20"
                : "border-sky-500/40 bg-sky-50/40 dark:bg-sky-950/20"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold">
                {locationResolution.level === 1 && "⚡ Level 1: TNPDCL GIS Lookup"}
                {locationResolution.level === 2 && "⚡ Level 2: Meter Repository"}
                {locationResolution.level === 3 && "📍 Level 3: Address Geocoding"}
                {locationResolution.level === 4 && "🛰️ Level 4: User-Confirmed"}
              </span>
              <span
                className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded ${
                  locationResolution.confidence >= 0.85
                    ? "bg-emerald-200 text-emerald-900 dark:bg-emerald-800 dark:text-emerald-100"
                    : "bg-amber-200 text-amber-900 dark:bg-amber-800 dark:text-amber-100"
                }`}
              >
                {Math.round(locationResolution.confidence * 100)}% Confidence
              </span>
            </div>

            {/* Score breakdown tags */}
            {locationResolution.score_breakdown && (
              <div className="flex flex-wrap gap-1 text-[10px] font-mono text-ink-muted">
                {locationResolution.score_breakdown.building_match > 0 && (
                  <span className="bg-ink/5 px-1 rounded text-emerald-700 dark:text-emerald-300">
                    Building: +{locationResolution.score_breakdown.building_match}
                  </span>
                )}
                {locationResolution.score_breakdown.street_match > 0 && (
                  <span className="bg-ink/5 px-1 rounded text-sky-700 dark:text-sky-300">
                    Street: +{locationResolution.score_breakdown.street_match}
                  </span>
                )}
                {locationResolution.score_breakdown.locality_match > 0 && (
                  <span className="bg-ink/5 px-1 rounded text-sky-700 dark:text-sky-300">
                    Locality: +{locationResolution.score_breakdown.locality_match}
                  </span>
                )}
                {locationResolution.score_breakdown.section_match > 0 && (
                  <span className="bg-ink/5 px-1 rounded text-purple-700 dark:text-purple-300">
                    Section: +{locationResolution.score_breakdown.section_match}
                  </span>
                )}
                {locationResolution.score_breakdown.pin_match > 0 && (
                  <span className="bg-ink/5 px-1 rounded text-amber-700 dark:text-amber-300">
                    PIN: +{locationResolution.score_breakdown.pin_match}
                  </span>
                )}
              </div>
            )}

            <p className="text-[11px] text-ink-sub leading-tight">
              {locationResolution.details}
            </p>

            {/* Distance check if user provided GPS */}
            {locationResolution.user_distance_meters != null && (
              <div className="flex items-center gap-1.5 text-xs font-mono">
                <span className="text-ink-muted">GPS comparison:</span>
                {locationResolution.user_distance_check === "likely" ? (
                  <span className="text-emerald-700 dark:text-emerald-300 font-semibold">
                    {locationResolution.user_distance_meters} m away — likely ✅
                  </span>
                ) : locationResolution.user_distance_check === "suspicious" ? (
                  <span className="text-rose-700 dark:text-rose-300 font-semibold">
                    {(locationResolution.user_distance_meters / 1000).toFixed(1)} km away — suspicious ❌
                  </span>
                ) : (
                  <span className="text-amber-700 dark:text-amber-300">
                    {locationResolution.user_distance_meters} m away
                  </span>
                )}
              </div>
            )}

            {/* Confirmation Callout and Actions if required */}
            {locationResolution.requires_user_confirmation && (
              <div className="pt-1.5 space-y-1.5 border-t border-amber-500/20">
                <p className="text-[11px] text-amber-900 dark:text-amber-200 font-medium">
                  Confidence is below 85%. Tap or drag the pin on the map to your exact roof, or verify with your device GPS.
                </p>
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    onClick={onRequestUserGps}
                    className="flex-1 py-1.5 px-2 rounded bg-sky-600 hover:bg-sky-700 text-white text-xs font-medium flex items-center justify-center gap-1 cursor-pointer transition"
                  >
                    <span>📍 Verify with My GPS</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => onConfirmLocation?.()}
                    className="flex-1 py-1.5 px-2 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium flex items-center justify-center gap-1 cursor-pointer transition"
                  >
                    <span>🏠 Confirm Location</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tamil Nadu Service Connection Identification Card */}
        <div className="rounded border border-amber-500/30 bg-amber-50/40 dark:bg-amber-950/20 p-2.5 space-y-2">
          <div className="flex items-center justify-between">
            <span className="caption font-semibold text-amber-900 dark:text-amber-300 flex items-center gap-1.5">
              ⚡ TNEB / TNPDCL Connection
            </span>
            {value.consumer_number && (
              <span className="text-code-mono font-mono text-xs bg-amber-200/80 dark:bg-amber-800/60 px-1.5 py-0.5 rounded text-amber-950 dark:text-amber-100 font-bold">
                {value.consumer_number}
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <span className="text-ink-muted block text-code-mono">Section</span>
              <input
                type="text"
                placeholder="e.g. GANDHI NAGAR / EAST"
                className="field mt-0.5 text-xs py-1 px-1.5 w-full"
                value={value.section ?? ""}
                onChange={(e) => onChange({ ...value, section: e.target.value })}
              />
            </div>
            <div>
              <span className="text-ink-muted block text-code-mono">Circle</span>
              <input
                type="text"
                placeholder="e.g. VELLORE"
                className="field mt-0.5 text-xs py-1 px-1.5 w-full"
                value={value.circle ?? ""}
                onChange={(e) => onChange({ ...value, circle: e.target.value })}
              />
            </div>
            <div>
              <span className="text-ink-muted block text-code-mono">Distribution</span>
              <input
                type="text"
                placeholder="e.g. E.B"
                className="field mt-0.5 text-xs py-1 px-1.5 w-full"
                value={value.distribution ?? ""}
                onChange={(e) => onChange({ ...value, distribution: e.target.value })}
              />
            </div>
            <div>
              <span className="text-ink-muted block text-code-mono">Consumer / Service No.</span>
              <input
                type="text"
                placeholder="e.g. 08-211-019-1233"
                className="field mt-0.5 text-xs py-1 px-1.5 w-full font-mono font-medium"
                value={value.consumer_number ?? ""}
                onChange={(e) => onChange({ ...value, consumer_number: e.target.value })}
              />
            </div>
          </div>

          {(value.bill_address || value.consumer_address || value.section || value.consumer_number) && (
            <button
              type="button"
              onClick={() => {
                onLocateAddress?.(value);
              }}
              className="w-full mt-1.5 py-2 px-3 bg-amber-600 hover:bg-amber-700 active:bg-amber-800 text-white rounded text-xs font-medium flex items-center justify-center gap-1.5 shadow-sm transition cursor-pointer"
            >
              <span>📍 Locate Connection on Map:</span>
              <span className="truncate max-w-[200px] underline font-bold">
                {value.consumer_number || value.consumer_address || value.bill_address || value.section}
              </span>
            </button>
          )}
        </div>

        <div className="rounded border border-dashed border-rail p-2.5">
          <label htmlFor="billfile" className="caption block">
            Or upload a bill to fill these in
          </label>
          <input
            id="billfile"
            type="file"
            accept="image/*,application/pdf"
            className="mt-1.5 text-code-mono file:mr-2 file:rounded file:border-0 file:bg-ink file:px-2 file:py-1 file:font-sans file:text-code-mono file:text-white disabled:opacity-50"
            onChange={handleFile}
            disabled={extracting || !canExtract}
          />
          <p className="mt-1 text-code-mono leading-4 text-ink-muted">
            {canExtract
              ? "Optional. We read the values, fill the fields above for you to check, and discard the file. It is never stored."
              : "Reading a bill needs the server, and it is unreachable. Type the two values above — that path always works and is the one the calculation uses either way."}
          </p>
          {extracting && <p className="mt-1.5 text-code-mono text-ink-sub">Reading…</p>}
          {extractError && <p className="notice notice-warn mt-1.5">{extractError}</p>}
        </div>

        {warnings.length > 0 && (
          <div className="notice notice-warn">
            <p className="font-medium">Check these before continuing</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-3.5">
              {warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Panel>
  );
}
