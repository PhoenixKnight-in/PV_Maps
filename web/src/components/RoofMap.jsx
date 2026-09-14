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

/** Modules render dark and cool against the warm roof amber, because on
 *  satellite imagery a panel IS the dark rectangle — matching that reads as the
 *  real thing rather than as an annotation layer. */
const PANEL_FILL = "#1e3a8a";
const PANEL_LINE = "#93c5fd";
const USABLE_LINE = "#16a34a";

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
  return seen
    ? [
        [w, s],
        [e, n],
      ]
    : null;
}

export default function RoofMap({
  building,
  center,
  label,
  fill = false,
  candidates = null,
  chosenIndex = null,
  layout = null,
  onPickCandidate = null,
  onPickPoint = null,
}) {
  const ref = useRef(null);
  const map = useRef(null);
  const markerRef = useRef(null);

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
          {
            id: "bg",
            type: "background",
            paint: { "background-color": "#f1f5f9" },
          },
          ...(BASEMAP_URL
            ? [
                {
                  id: "satellite",
                  type: "raster",
                  source: "satellite",
                  paint: { "raster-opacity": 1 },
                },
              ]
            : []),
        ],
      },
      center: lon != null && lat != null ? [lon, lat] : [79.13, 12.92],
      // FR-1.1 works the imagery at z19–20. At z17 a 10 m terrace is about
      // nine pixels across, which is not a roof anyone can confirm.
      zoom: 19,
      attributionControl: true,
    });
    // A basemap that cannot load must say so somewhere. `ErrorBoundary quiet`
    // wraps this component, so without a listener a style failure is invisible.
    m.on("error", (e) => console.warn("[RoofMap]", e?.error?.message ?? e));
    m.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "top-right",
    );
    m.addControl(
      new maplibregl.ScaleControl({ maxWidth: 90, unit: "metric" }),
      "bottom-left",
    );
    map.current = m;
    return () => {
      markerRef.current?.remove();
      markerRef.current = null;
      map.current?.remove();
      map.current = null;
    };
    // Created once, deliberately. This effect used to depend on [lon, lat],
    // which destroyed and rebuilt the whole map -- and every layer on it --
    // each time an address resolved. That was survivable when the map only
    // appeared after a parcel was chosen; now that it is always on screen and
    // the user flies between addresses, it would blank the canvas on every
    // search. Recentring belongs in the flyTo effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // MapLibre measures its container once, at construction, and never again on
  // its own. That was invisible while the canvas was `absolute inset-0` and
  // therefore had its final size immediately; as a sticky grid column it is laid
  // out AFTER mount, so the map kept the size it saw first — zero — and rendered
  // a blank grey box with working controls sitting on top of it.
  useEffect(() => {
    const m = map.current;
    const el = ref.current;
    if (!m || !el || typeof ResizeObserver === "undefined") return;

    // NEVER resize before the style has loaded. Calling resize() mid-load leaves
    // the map with no source caches and `isStyleLoaded()` stuck false: no tiles
    // are ever requested, flyTo silently does nothing, and what is on screen is
    // a grey box with working zoom buttons sitting on top of it. Observed
    // 2026-09-14 — getStyle() returned undefined on the affected instance.
    const safeResize = () => {
      try {
        m.resize();
      } catch {
        // Resizing a torn-down map is not worth surfacing.
      }
    };

    const ro = new ResizeObserver(() => {
      if (m.isStyleLoaded()) safeResize();
    });
    ro.observe(el);

    if (m.isStyleLoaded()) safeResize();
    else m.once("load", safeResize);

    return () => ro.disconnect();
  }, []);

  // Recentre and reposition draggable pin without remounting.
  useEffect(() => {
    const m = map.current;
    if (!m || lon == null || lat == null) return;
    // `essential` so the flight still runs under prefers-reduced-motion: the
    // camera move IS the feedback that the address resolved.
    m.flyTo({ center: [lon, lat], zoom: 19, duration: 900, essential: true });

    if (!markerRef.current) {
      const el = document.createElement("div");
      el.className = "cursor-grab active:cursor-grabbing";
      el.title = "Drag this pin to your exact roof";
      el.innerHTML = `
        <div style="display: flex; flex-direction: column; align-items: center; filter: drop-shadow(0 4px 6px rgba(0,0,0,0.35)); cursor: grab;">
          <div style="background: #f59e0b; color: white; border: 2.5px solid white; border-radius: 9999px; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; font-size: 16px; box-shadow: 0 0 10px rgba(245, 158, 11, 0.6);">
            📍
          </div>
          <div style="width: 2px; height: 8px; background: #b45309;"></div>
        </div>
      `;
      const marker = new maplibregl.Marker({
        element: el,
        draggable: true,
      })
        .setLngLat([lon, lat])
        .addTo(m);

      marker.on("dragend", () => {
        const lngLat = marker.getLngLat();
        onPickPoint?.(lngLat.lat, lngLat.lng);
      });
      markerRef.current = marker;
    } else {
      markerRef.current.setLngLat([lon, lat]);
    }
  }, [lon, lat, onPickPoint]);

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
        m.addSource("obstructions", {
          type: "geojson",
          data: building.obstruction_geojson,
        });
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

  // Live SAM2 candidates. The chosen one is drawn solid; the alternatives sit
  // underneath as dashed outlines the user can tap.
  //
  // FR-1.5 requires the assumption to be correctable, and here that is literal:
  // SAM2 returns the same point at several nested scales and its own confidence
  // cannot tell a rooftop from the courtyard kiosk on it. Showing only the pick
  // would hide the one control that makes a wrong pick recoverable.
  useEffect(() => {
    const m = map.current;
    if (!m) return;

    const draw = () => {
      for (const id of ["cand-line", "cand-fill", "cand-alt-line"]) {
        if (m.getLayer(id)) m.removeLayer(id);
      }
      if (m.getSource("candidates")) m.removeSource("candidates");
      if (!candidates?.length) return;

      m.addSource("candidates", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: candidates.map((c, i) => ({
            type: "Feature",
            geometry: c.geometry,
            properties: {
              i,
              chosen: i === chosenIndex ? 1 : 0,
              area: c.area_m2,
            },
          })),
        },
      });

      m.addLayer({
        id: "cand-alt-line",
        type: "line",
        source: "candidates",
        filter: ["==", ["get", "chosen"], 0],
        paint: {
          "line-color": ROOF_LINE,
          "line-width": 1.25,
          "line-opacity": 0.55,
          "line-dasharray": [2, 2],
        },
      });
      m.addLayer({
        id: "cand-fill",
        type: "fill",
        source: "candidates",
        filter: ["==", ["get", "chosen"], 1],
        paint: { "fill-color": ROOF_FILL, "fill-opacity": 0.3 },
      });
      m.addLayer({
        id: "cand-line",
        type: "line",
        source: "candidates",
        filter: ["==", ["get", "chosen"], 1],
        paint: { "line-color": ROOF_LINE, "line-width": 2 },
      });

      const chosen = chosenIndex != null ? candidates[chosenIndex] : null;
      const b = chosen && bounds(chosen.geometry);
      if (b) m.fitBounds(b, { padding: 64, maxZoom: 20, duration: 600 });
    };

    if (m.isStyleLoaded()) draw();
    else m.once("load", draw);
  }, [candidates, chosenIndex]);

  // The usable plane and the modules that fit on it.
  //
  // This is the answer to "show me where the panels actually go". The candidate
  // outline is the FOOTPRINT; the green line inside it is what survives the
  // parapet setback, and the dark rectangles are real module footprints packed
  // into that, at the tilt and row pitch the yield model assumed.
  useEffect(() => {
    const m = map.current;
    if (!m) return;

    const draw = () => {
      for (const id of ["panel-fill", "panel-line", "usable-line"]) {
        if (m.getLayer(id)) m.removeLayer(id);
      }
      for (const id of ["panels", "usable"]) {
        if (m.getSource(id)) m.removeSource(id);
      }
      if (!layout) return;

      if (layout.usable_geometry) {
        m.addSource("usable", {
          type: "geojson",
          data: layout.usable_geometry,
        });
        m.addLayer({
          id: "usable-line",
          type: "line",
          source: "usable",
          paint: {
            "line-color": USABLE_LINE,
            "line-width": 1.5,
            "line-dasharray": [3, 2],
          },
        });
      }

      if (layout.panels?.features?.length) {
        m.addSource("panels", { type: "geojson", data: layout.panels });
        m.addLayer({
          id: "panel-fill",
          type: "fill",
          source: "panels",
          paint: { "fill-color": PANEL_FILL, "fill-opacity": 0.75 },
        });
        // Hairline edges, so a dense array still reads as separate modules
        // rather than one dark blob at the zoom a roof is confirmed at.
        m.addLayer({
          id: "panel-line",
          type: "line",
          source: "panels",
          paint: { "line-color": PANEL_LINE, "line-width": 0.5 },
        });
      }
    };

    if (m.isStyleLoaded()) draw();
    else m.once("load", draw);
  }, [layout]);

  // ONE click handler, because the map has two meanings for a click and they
  // must not both fire. MapLibre delivers every listener the same event and has
  // no preventDefault, so tapping an outline would otherwise also re-measure
  // the point under it -- throwing away the choice the user just made and
  // spending a GPU round trip to do it.
  //
  // Outlines win: aiming at a drawn shape is a more specific intention than
  // aiming at the ground.
  useEffect(() => {
    const m = map.current;
    if (!m || (!onPickCandidate && !onPickPoint)) return;

    const handler = (e) => {
      const layers = ["cand-alt-line", "cand-fill", "cand-line"].filter((l) =>
        m.getLayer(l),
      );
      const hit = layers.length
        ? m.queryRenderedFeatures(e.point, { layers })
        : [];
      if (hit.length && onPickCandidate) {
        onPickCandidate(hit[0].properties.i);
        return;
      }
      onPickPoint?.(e.lngLat.lat, e.lngLat.lng);
      if (markerRef.current) {
        markerRef.current.setLngLat([e.lngLat.lng, e.lngLat.lat]);
      }
    };

    m.on("click", handler);
    if (onPickPoint) m.getCanvas().style.cursor = "crosshair";
    return () => {
      m.off("click", handler);
      const c = m.getCanvas?.();
      if (c) c.style.cursor = "";
    };
  }, [onPickCandidate, onPickPoint, candidates]);

  if (fill) {
    // Workstation backdrop: the canvas the floating columns sit over.
    return (
      <div className="relative h-full w-full">
        <div ref={ref} className="h-full w-full" />
        {/* Reticle / Pin instruction prompt */}
        <div className="hud pointer-events-none absolute top-3 left-1/2 -translate-x-1/2 z-10 flex items-center gap-1.5 px-3.5 py-1.5 bg-white/95 backdrop-blur-sm shadow-md rounded-full border border-amber-500/40 text-xs font-sans">
          <span className="text-amber-600 font-semibold flex items-center gap-1">
            <span className="animate-pulse">🎯</span> Tap or drag pin
          </span>
          <span className="text-ink-muted">onto your exact roof</span>
        </div>
      </div>
    );
  }

  return (
    <div className="relative overflow-hidden rounded-lg border border-hairline">
      <div ref={ref} className="h-[320px] w-full lg:h-[420px]" />

      {/* Reticle / Pin instruction prompt */}
      <div className="hud pointer-events-none absolute top-3 left-1/2 -translate-x-1/2 z-10 flex items-center gap-1.5 px-3.5 py-1.5 bg-white/95 backdrop-blur-sm shadow-md rounded-full border border-amber-500/40 text-xs font-sans">
        <span className="text-amber-600 font-semibold flex items-center gap-1">
          <span className="animate-pulse">🎯</span> Tap or drag pin
        </span>
        <span className="text-ink-muted">onto your exact roof</span>
      </div>

      {/* Address pill. The live dot marks a resolved pilot address rather than
          a guess from a live geocoder — there isn't one. */}
      {label && (
        <div className="hud pointer-events-none absolute left-3 top-3 flex max-w-[calc(100%-5rem)] items-center gap-2 px-2.5 py-1.5">
          <span className="chip-dot bg-sky" aria-hidden="true" />
          {/* One line, truncated. Pilot display names run long, and a wrapping
              pill grows into the zoom stack on a phone. */}
          <span
            className="truncate font-mono text-code-mono font-medium text-ink"
            title={label}
          >
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
              <span
                className="h-2 w-2 rounded-sm bg-solar"
                aria-hidden="true"
              />
              Roof plane
            </span>
            {building.obstruction_geojson && (
              <span className="flex items-center gap-1">
                <span
                  className="h-2 w-2 rounded-sm bg-critical"
                  aria-hidden="true"
                />
                Obstruction
              </span>
            )}
          </p>
        </div>
      )}
    </div>
  );
}
