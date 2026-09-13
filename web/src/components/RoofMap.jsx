import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

/**
 * ARCHITECTURE.md 4.1 step 2 — imagery plus the extracted roof polygon.
 *
 * The map is a confidence device, not a calculation input. If it fails to load,
 * the result must still render — which is exactly why ARCHITECTURE.md 10 builds
 * the result screen (item 5) before the map (item 6).
 *
 * Layer colours carry the palette's meanings: the roof plane is solar amber,
 * detected obstructions are constraint crimson. Feeder cyan is not used — it
 * means distribution-transformer infrastructure, and Phase 1 has none.
 *
 * The HUD follows Stitch Project A: address pill top-left, zoom top-right,
 * scale bottom-left. Zoom and scale are MapLibre's own controls rather than
 * bespoke chrome, so they stay honest about what the viewport is actually doing.
 */
/**
 * Basemap imagery.
 *
 * ARCHITECTURE.md 9.3 wants no external network dependency on stage, and that
 * constraint is why this was a flat fill for so long. It is now a switch rather
 * than an absence:
 *
 *   VITE_BASEMAP_URL=""      flat field, zero network — the stage-safe demo
 *   VITE_BASEMAP_URL=<tpl>   raster imagery from that template
 *
 * The default is Esri World Imagery: keyless, attributed below, and carrying
 * z19–20 coverage over the Vellore pilot, which FR-1.1 needs — at z17 a 10 m
 * terrace is nine pixels across and nobody can confirm a roof from it.
 *
 * To honour 9.3 completely, serve equivalent tiles from our own origin and
 * point this at them; nothing else in this file changes.
 */
const BASEMAP_URL =
  import.meta.env.VITE_BASEMAP_URL ??
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";

const BASEMAP_ATTRIBUTION =
  import.meta.env.VITE_BASEMAP_ATTRIBUTION ??
  "Imagery © Esri, Maxar, Earthstar Geographics";

const SATELLITE_SOURCE = {
  type: "raster",
  tiles: [BASEMAP_URL],
  tileSize: 256,
  // Esri publishes to 19 for much of India and higher in places. Declaring the
  // true ceiling lets MapLibre overzoom the last real tile instead of asking
  // for one that does not exist and leaving a hole in the roof we are asking
  // the household to confirm.
  maxzoom: 19,
  attribution: BASEMAP_ATTRIBUTION,
};

/* Grid Spatial Studio semantics: solar generation amber for the active
   roof plane, critical red for obstruction cut-outs. */
const ROOF_FILL = "#d97706";
const ROOF_LINE = "#b45309";
const OBSTRUCTION = "#dc2626";

/** [[w, s], [e, n]] over any GeoJSON coordinate nesting, or null if empty. */
function bounds(geojson) {
  let w = 180;
  let s = 90;
  let e = -180;
  let n = -90;
  let seen = false;

  const walk = (c) => {
    if (typeof c?.[0] === "number") {
      seen = true;
      w = Math.min(w, c[0]);
      e = Math.max(e, c[0]);
      s = Math.min(s, c[1]);
      n = Math.max(n, c[1]);
      return;
    }
    if (Array.isArray(c)) c.forEach(walk);
  };

  walk(geojson?.coordinates ?? geojson?.geometry?.coordinates);
  return seen ? [[w, s], [e, n]] : null;
}

export default function RoofMap({ building, center, label, fill = false }) {
  const ref = useRef(null);
  const map = useRef(null);

  // Primitives, not the array. `center={[lon, lat]}` is a new array on every
  // render, and keying the creation effect on it destroyed and rebuilt the map
  // each time — taking the roof and obstruction layers with it.
  const lon = center?.[0];
  const lat = center?.[1];

  useEffect(() => {
    if (!ref.current || map.current) return;
    const m = new maplibregl.Map({
      container: ref.current,
      style: {
        version: 8,
        sources: BASEMAP_URL ? { satellite: SATELLITE_SOURCE } : {},
        // The flat field stays as the base layer even when imagery is on: it is
        // what a viewer sees while tiles are in flight, and what they keep
        // seeing if the tile host is unreachable. A failed basemap degrades to
        // the old behaviour rather than to a black hole.
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#f1f5f9" } },
          ...(BASEMAP_URL
            ? [{ id: "satellite", type: "raster", source: "satellite", paint: { "raster-opacity": 1 } }]
            : []),
        ],
      },
      center: lon != null && lat != null ? [lon, lat] : [79.13, 12.92],
      // FR-1.1 works the imagery at z19–20. At z17 a 10 m terrace is about
      // nine pixels across, which is not a roof anyone can confirm.
      zoom: 19,
      attributionControl: true,
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.addControl(new maplibregl.ScaleControl({ maxWidth: 90, unit: "metric" }), "bottom-left");
    map.current = m;
    return () => {
      map.current?.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lon, lat]);

  useEffect(() => {
    const m = map.current;
    if (!m || !building?.geojson) return;

    const draw = () => {
      for (const id of ["roof-fill", "roof-line", "obstruction-fill"]) {
        if (m.getLayer(id)) m.removeLayer(id);
      }
      for (const id of ["roof", "obstructions"]) {
        if (m.getSource(id)) m.removeSource(id);
      }

      m.addSource("roof", { type: "geojson", data: building.geojson });
      m.addLayer({
        id: "roof-fill",
        type: "fill",
        source: "roof",
        paint: { "fill-color": ROOF_FILL, "fill-opacity": 0.3 },
      });
      m.addLayer({
        id: "roof-line",
        type: "line",
        source: "roof",
        paint: { "line-color": ROOF_LINE, "line-width": 1.5 },
      });

      // Frame the roof. "Is this your roof?" is only answerable if the outline
      // fills the viewport, and footprints vary from a 60 m² terrace to a
      // 1,300 m² institutional block — one fixed zoom cannot serve both.
      const b = bounds(building.geojson);
      if (b) m.fitBounds(b, { padding: 56, maxZoom: 20, duration: 0 });

      if (building.obstruction_geojson) {
        m.addSource("obstructions", { type: "geojson", data: building.obstruction_geojson });
        m.addLayer({
          id: "obstruction-fill",
          type: "fill",
          source: "obstructions",
          paint: { "fill-color": OBSTRUCTION, "fill-opacity": 0.45 },
        });
      }
    };

    if (m.isStyleLoaded()) draw();
    else m.once("load", draw);
  }, [building]);

  if (fill) {
    // Workstation backdrop: the canvas the floating columns sit over.
    return <div ref={ref} className="h-full w-full" />;
  }

  return (
    <div className="relative overflow-hidden rounded-lg border border-hairline">
      <div ref={ref} className="h-[320px] w-full lg:h-[420px]" />

      {/* Address pill. The live dot marks a resolved pilot address rather than
          a guess from a live geocoder — there isn't one. */}
      {label && (
        <div className="hud pointer-events-none absolute left-3 top-3 flex max-w-[calc(100%-5rem)] items-center gap-2 px-2.5 py-1.5">
          <span className="chip-dot bg-sky" aria-hidden="true" />
          {/* One line, truncated. Pilot display names run long, and a wrapping
              pill grows into the zoom stack on a phone. */}
          <span className="truncate font-mono text-code-mono font-medium text-ink" title={label}>
            {label}
          </span>
        </div>
      )}

      {/* Layer legend. Sits bottom-right so it never collides with the scale
          bar or the zoom stack. */}
      {building && (
        <div className="hud pointer-events-none absolute bottom-9 right-3 px-2 py-1">
          <p className="flex items-center gap-3 text-code-mono text-ink-sub">
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-sm bg-solar" aria-hidden="true" />
              Roof plane
            </span>
            {building.obstruction_geojson && (
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-sm bg-critical" aria-hidden="true" />
                Obstruction
              </span>
            )}
          </p>
        </div>
      )}
    </div>
  );
}
