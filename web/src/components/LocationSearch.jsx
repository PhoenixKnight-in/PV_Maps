import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { dataSource } from "../api/dataSource";
import Chip from "./ui/Chip";

/**
 * Find any address, not one of five.
 *
 * Two sources, queried together and shown in one list:
 *
 *   PILOT   the seeded roofs. Hand-checked areas, a stored bill scenario, and
 *           a precomputed pvlib yield. Always ranked first when they match.
 *   MAPPED  anything Nominatim can resolve in India. No roof attached yet --
 *           that is what the live measurement step is for.
 *
 * Keeping both matters. A pilot roof answers faster and with better provenance,
 * so demoting it to "just another geocoder hit" would lose the one part of this
 * product that has been checked by a human.
 */
export default function LocationSearch({ onPick, selected, busy = false }) {
  const [q, setQ] = useState("");
  const [pilot, setPilot] = useState([]);
  const [places, setPlaces] = useState([]);
  const [cursor, setCursor] = useState(0);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState(null);
  const [locating, setLocating] = useState(false);
  const seq = useRef(0);

  function locateMe() {
    if (!navigator.geolocation) {
      setError("Geolocation is not supported by your browser.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        choose({
          kind: "MAPPED",
          label: "Current GPS Location",
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
        });
      },
      (err) => {
        setLocating(false);
        setError("Unable to retrieve location: " + err.message);
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  }

  useEffect(() => {
    if (q.trim().length < 3) {
      setPilot([]);
      setPlaces([]);
      setSearched(false);
      setSearching(false);
      return;
    }
    setSearching(true);
    const mine = ++seq.current;
    const t = setTimeout(async () => {
      // Settled, not all: a geocoder outage must not hide a pilot roof that
      // matched, and vice versa.
      const [p, g] = await Promise.allSettled([
        dataSource.searchAddresses(q),
        api.geocode(q),
      ]);
      if (mine !== seq.current) return; // a newer keystroke already won
      setPilot(p.status === "fulfilled" ? p.value : []);
      setPlaces(g.status === "fulfilled" ? g.value : []);
      setError(
        g.status === "rejected" && p.status === "rejected"
          ? "Address lookup is unavailable. Drop a pin on the map instead."
          : null,
      );
      setCursor(0);
      setSearched(true);
      setSearching(false);
    }, 450); // Snappy debounce for search
    return () => clearTimeout(t);
  }, [q]);

  const rows = [
    ...pilot.map((a) => ({
      kind: "PILOT",
      label: a.display_name,
      lat: a.lat,
      lon: a.lon,
      address: a,
    })),
    ...places.map((h) => ({
      kind: "MAPPED",
      label: h.display_name,
      lat: h.lat,
      lon: h.lon,
      broadenedTo: h.matched_query ?? null,
    })),
  ];

  function choose(row) {
    if (!row) return;
    onPick(row);
    setPilot([]);
    setPlaces([]);
    setSearched(false);
    setQ("");
  }

  function onKeyDown(e) {
    if (!rows.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => (c + 1) % rows.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => (c - 1 + rows.length) % rows.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(rows[cursor]);
    } else if (e.key === "Escape") {
      setPilot([]);
      setPlaces([]);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <label htmlFor="loc" className="caption">
          Find a roof
        </label>
        <span className="mono text-code-mono text-ink-subtle">
          {busy
            ? "measuring…"
            : searching
              ? "searching…"
              : `${rows.length || "—"} matches`}
        </span>
      </div>

      <div className="relative mt-1 flex gap-1.5 items-center">
        <div className="relative flex-1">
          <input
            id="loc"
            className="field pl-7 font-sans w-full"
            placeholder="Address, door number, street, locality…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKeyDown}
            autoComplete="off"
            role="combobox"
            aria-expanded={rows.length > 0}
            aria-controls="loc-results"
          />
          <span
            className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 font-mono text-code-mono text-ink-subtle"
            aria-hidden="true"
          >
            ⌕
          </span>
        </div>
        <button
          type="button"
          onClick={locateMe}
          title="Pinpoint current GPS location"
          className="btn-subtle px-2.5 py-1.5 text-xs flex items-center gap-1 shrink-0 h-[34px]"
          disabled={locating}
        >
          {locating ? "📍…" : "📍 GPS"}
        </button>
      </div>

      {error && (
        <p className="mt-1 text-code-mono leading-4 text-critical">{error}</p>
      )}

      {!error && searched && !searching && rows.length === 0 && (
        <p className="mt-1.5 text-code-mono leading-4 text-ink-muted">
          Nothing found. Try adding the town, or drop a pin directly on the map.
        </p>
      )}

      {rows.length > 0 && (
        <ul
          id="loc-results"
          role="listbox"
          className="mt-1.5 max-h-64 overflow-y-auto rounded border border-rail bg-surface"
        >
          {rows.map((row, i) => (
            <li
              key={`${row.kind}-${row.label}-${i}`}
              className="border-b border-well last:border-0"
            >
              <button
                type="button"
                role="option"
                aria-selected={i === cursor}
                className={`flex w-full items-start gap-2 px-2 py-1.5 text-left transition ${
                  i === cursor ? "bg-sky-tint" : "hover:bg-canvas"
                }`}
                onMouseEnter={() => setCursor(i)}
                onClick={() => choose(row)}
              >
                <span className="mt-0.5 shrink-0">
                  <Chip tone={row.kind === "PILOT" ? "ok" : "neutral"}>
                    {row.kind === "PILOT" ? "Pilot" : "Map"}
                  </Chip>
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-body-sm leading-5 text-ink">
                    {row.label}
                  </span>
                  <span className="mono block text-code-mono text-ink-subtle">
                    {Number(row.lat).toFixed(4)}, {Number(row.lon).toFixed(4)}
                  </span>
                  {/* An exact address that OSM does not hold falls back to the
                      street or the town. Saying so is the difference between a
                      pin the user trusts and one they should move. */}
                  {row.broadenedTo && (
                    <span className="mt-0.5 block text-code-mono leading-4 text-solar-deep">
                      Broadened to “{row.broadenedTo}” — tap your own roof on
                      the map once you get there.
                    </span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {selected && rows.length === 0 && (
        <div className="mt-2 rounded border border-hairline bg-canvas px-2 py-1.5">
          <div className="flex items-center gap-1.5">
            <span className="chip-dot bg-sky" aria-hidden="true" />
            <span className="caption">Resolved target</span>
          </div>
          <p className="mt-1 text-body-sm leading-5 text-ink">
            {selected.label}
          </p>
          <p className="mono mt-0.5 text-code-mono text-ink-muted">
            {Number(selected.lat).toFixed(4)}° N,{" "}
            {Number(selected.lon).toFixed(4)}° E
          </p>
        </div>
      )}
    </div>
  );
}
