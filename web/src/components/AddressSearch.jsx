import { useEffect, useRef, useState } from "react";
import { dataSource, useDataState } from "../api/dataSource";
import Chip from "./ui/Chip";

/**
 * ARCHITECTURE.md 4.1 step 1 — find a precomputed pilot address.
 *
 * Resolves against our own table (pg_trgm), so there is no live geocoder to
 * fail on stage. Presented as a workstation locator rather than a generic
 * search box: mono input, a result list that is keyboard-navigable, and a
 * resolved-target readout with coordinates once a parcel is selected.
 */
export default function AddressSearch({ onSelect, selected }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const [cursor, setCursor] = useState(0);
  const [error, setError] = useState(null);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const boxRef = useRef(null);
  const { mode } = useDataState();
  const offline = mode === "FALLBACK";

  useEffect(() => {
    if (q.trim().length < 3) {
      setResults([]);
      setSearching(false);
      setSearched(false);
      return;
    }
    setSearching(true);
    const t = setTimeout(() => {
      // dataSource, not api: when the geocoding route fails this resolves
      // against the bundled pilot addresses instead (ARCHITECTURE.md 9.3).
      dataSource
        .searchAddresses(q)
        .then((r) => {
          setResults(r);
          setCursor(0);
          setError(null);
          setSearched(true);
        })
        .catch((e) => setError(e.message))
        .finally(() => setSearching(false));
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  function choose(a) {
    onSelect(a);
    setResults([]);
    setSearched(false);
    setQ("");
  }

  function onKeyDown(e) {
    if (!results.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => (c + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => (c - 1 + results.length) % results.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(results[cursor]);
    } else if (e.key === "Escape") {
      setResults([]);
    }
  }

  return (
    <div ref={boxRef}>
      <div className="flex items-center justify-between gap-2">
        <label htmlFor="addr" className="caption">
          Parcel locator
        </label>
        <span className="mono text-code-mono text-ink-subtle">
          {searching ? "searching…" : `${results.length || "—"} matches`}
        </span>
      </div>

      <div className="relative mt-1">
        <input
          id="addr"
          className="field pl-7 font-sans"
          placeholder="Vellore pilot address…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKeyDown}
          autoComplete="off"
          role="combobox"
          aria-expanded={results.length > 0}
          aria-controls="addr-results"
        />
        <span
          className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 font-mono text-code-mono text-ink-subtle"
          aria-hidden="true"
        >
          ⌕
        </span>
      </div>

      {error && <p className="mt-1 text-code-mono text-critical">{error}</p>}

      {/* An address outside the pilot has to read as "not covered", never as a
          broken search box — and offline that boundary is five rows wide. */}
      {!error && searched && !searching && results.length === 0 && (
        <p className="mt-1.5 text-code-mono leading-4 text-ink-muted">
          No pilot address matches that.{" "}
          {offline
            ? "Offline, only the five bundled pilot addresses can be resolved."
            : "PV Maps covers the Vellore Ward 12 pilot area only."}
        </p>
      )}

      {results.length > 0 && (
        <ul
          id="addr-results"
          role="listbox"
          className="mt-1.5 overflow-hidden rounded border border-rail bg-surface"
        >
          {results.map((a, i) => (
            <li key={a.id} className="border-b border-well last:border-0">
              <button
                type="button"
                role="option"
                aria-selected={i === cursor}
                className={`flex w-full items-baseline justify-between gap-2 px-2 py-1.5 text-left transition ${
                  i === cursor ? "bg-sky-tint" : "hover:bg-canvas"
                }`}
                onMouseEnter={() => setCursor(i)}
                onClick={() => choose(a)}
              >
                <span className="text-body-sm text-ink">{a.display_name}</span>
                <span className="mono shrink-0 text-code-mono text-ink-subtle">
                  {a.lat.toFixed(3)}, {a.lon.toFixed(3)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {selected && results.length === 0 && (
        <div className="mt-2 rounded border border-hairline bg-canvas px-2 py-1.5">
          <div className="flex items-center gap-1.5">
            <span className="chip-dot bg-sky" aria-hidden="true" />
            <span className="caption">Resolved target</span>
          </div>
          <p className="mt-1 text-body-sm text-ink">{selected.display_name}</p>
          <p className="mono mt-0.5 text-code-mono text-ink-muted">
            {selected.lat.toFixed(4)}° N, {selected.lon.toFixed(4)}° E
            {!selected.building_id && (
              <>
                {" "}
                <Chip tone="warn">No analysed roof</Chip>
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );
}
