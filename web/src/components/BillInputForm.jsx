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
export default function BillInputForm({ value, onChange, errors }) {
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState(null);
  const [extracted, setExtracted] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const { mode } = useDataState();

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
