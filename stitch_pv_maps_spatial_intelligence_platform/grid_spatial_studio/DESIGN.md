---
name: Grid Spatial Studio
colors:
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  on-surface: '#0b1c30'
  on-surface-variant: '#45464d'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#76777d'
  outline-variant: '#c6c6cd'
  surface-tint: '#565e74'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#131b2e'
  on-primary-container: '#7c839b'
  inverse-primary: '#bec6e0'
  secondary: '#006398'
  on-secondary: '#ffffff'
  secondary-container: '#5bb8fe'
  on-secondary-container: '#00476e'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#2f1500'
  on-tertiary-container: '#c76c00'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dae2fd'
  primary-fixed-dim: '#bec6e0'
  on-primary-fixed: '#131b2e'
  on-primary-fixed-variant: '#3f465c'
  secondary-fixed: '#cce5ff'
  secondary-fixed-dim: '#93ccff'
  on-secondary-fixed: '#001d31'
  on-secondary-fixed-variant: '#004b73'
  tertiary-fixed: '#ffdcc3'
  tertiary-fixed-dim: '#ffb77d'
  on-tertiary-fixed: '#2f1500'
  on-tertiary-fixed-variant: '#6e3900'
  background: '#f8f9ff'
  on-background: '#0b1c30'
  surface-variant: '#d3e4fe'
typography:
  display:
    fontFamily: Geist
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 34px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Geist
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.015em
  headline-lg-mobile:
    fontFamily: Geist
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 22px
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: -0.005em
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  metric-headline:
    fontFamily: JetBrains Mono
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.02em
  metric-label:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.02em
  caption:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.02em
  code-mono:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 0.75rem
  gutter-mobile: 0.5rem
  margin: 1rem
  margin-mobile: 0.75rem
  space-xs: 0.25rem
  space-sm: 0.375rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
---

## Brand & Style

This design system delivers a high-density, mission-critical workspace tailored for utility engineers, geospatial analysts, and energy dispatchers overseeing Tamil Nadu's energy distribution grid. The design style combines **Spatial Data Minimalism** with the surgical operational clarity of high-grade engineering cockpits:

- **Surgical Utility & High Density:** The user interface privileges information bandwidth over decorative white space. Visual elements recede behind live geospatial telemetry, single-line feeder diagrams, and power-flow vectors.
- **Restrained Glassmorphism & Tonal Structuralism:** Overlays, floating heads-up display (HUD) panels, and contextual inspectors leverage high-opacity frosted glass layers with structural 1px hairline dividers to preserve canvas context beneath complex vector layers.
- **Instrument-Grade Restraint:** Strictly no playful illustrations, exaggerated pill radii, or decorative color fills. Color acts solely as a semantic variable indicating phase balance, line capacity, telemetry health, and load anomalies.
- **Mission Context:** Built to sustain multi-hour cognitive endurance across multi-monitor dispatch configurations and rugged field tablets under shifting ambient sunlight.

## Colors

The system employs a disciplined, light-mode palette engineered for vector cartography, dense topological trees, and high-frequency telemetry tables.

### Base Canvas & Surfaces
- **Canvas Base:** `#f8fafc` (Slate 50) transitioning to `#f1f5f9` (Slate 100) for control wells, canvas rails, and secondary viewport gutters.
- **Panel Surface (Opaque):** `#ffffff` (Pure White), providing absolute contrast against geospatial vector geometry.
- **Panel Surface (Heads-Up Display Glass):** `rgba(255, 255, 255, 0.92)` with `12px` backdrop-filter blur and `1px` inner hair-line stroke of `rgba(255, 255, 255, 0.4)`.
- **Structural Hairlines:** `#e2e8f0` (Slate 200) for internal component cell separators; `#cbd5e1` (Slate 300) for perimeter viewports and docking rails.

### Core Ink & Metric Readability
- **Primary Ink:** `#0f172a` (Slate 900) for primary metrics, substation identifiers, and active state values.
- **Secondary Ink:** `#334155` (Slate 700) for high-importance labels, column titles, and panel headers.
- **Muted Ink:** `#64748b` (Slate 500) for tabular units, geographical coordinates, and timestamp metadata.
- **Subtle Ink:** `#94a3b8` (Slate 400) for inactive states, tick marks, and inactive grid lines.

### Semantic Telemetry & Network Accents
- **Technical Network / Primary Accent:** `#0284c7` (Sky 600) with deep anchor `#0369a1` (Sky 700) and soft substrate `#f0f9ff` (Sky 50) for active topology traces, live busbars, and selection rings.
- **Solar Generation / Amber Warning:** `#d97706` (Amber 600) with core tone `#b45309` (Amber 700) and light warning substrate `#fffbeb` (Amber 50) for sub-optimal capacity, solar array output, and thermal alerts.
- **Optimal / Connected / Safe:** `#059669` (Emerald 600) on `#ecfdf5` (Emerald 50) background, indicating balanced circuits and nominal frequency (50.0 Hz).
- **Critical / Fault / Breaker Trip:** `#dc2626` (Red 600) on `#fef2f2` (Red 50) background, reserved strictly for phase dropouts, transformer over-temperature, and active tripping.

## Typography

The typographic hierarchy implements a high-clarity dual-engine strategy: **Geist** for crisp structural layout and navigation; **Inter** for dense contextual operational prose; and **JetBrains Mono** with forced tabular figures (`tnum`, `zero`, `cv01`) for real-time electrical metrics, geographical coordinates, and timestamp logs.

### Rules of Usage
- **Tabular Numerals Everywhere:** All telemetry tables, busbar metrics (MW, MVAR, kV), timestamps, and coordinates must render in `JetBrains Mono` or `Inter` with `font-feature-settings: "tnum" 1, "cv05" 1`. Numbers must never wobble horizontally during live WebSocket stream refreshes.
- **All-Caps Micro Labels:** `metric-label` and `caption` styles applied to sensor names and phase rings (e.g., `PHASE A`, `FEEDER-400KV-KANCHEEPURAM`) must be styled in uppercase with a `+0.04em` tracking allowance for rapid peripheral scanning.
- **Weight Restraint:** Never exceed weight `600` (Semi-Bold). Structural weight is achieved through tonal contrast rather than heavy visual mass.

## Layout & Spacing

The layout model is governed by a full-bleed, docking-rail spatial grid designed to support an uninterrupted map surface while hosting collapsible data wings:

- **Docking Rails & Fluid Viewport:** The primary GIS canvas occupies `100vw × 100vh`. Left-hand topology trees dock at a fixed `320px` width; right-hand analytical telemetry inspectors dock at `380px`. The center viewport remains purely fluid.
- **Rhythm & Grid:** Built on an exacting 4px baseline subgrid. The internal element gap standard is `0.375rem` (6px) or `0.75rem` (12px), eliminating superfluous padding to ensure maximum row-visibility in telemetry tables without requiring scroll gestures.
- **Responsive Adaptation:**
  - **Desktop (≥ 1280px):** Permanent dual-dock layout with persistent floating spatial toolbar (`44px` height).
  - **Tablet Field View (768px – 1279px):** Side panels collapse into off-canvas sliding overlays (`width: 360px`, `z-index: 40`), leaving spatial viewport tap targets touch-optimized (`min-height: 44px`).
  - **Mobile Field Terminal (< 768px):** Single-column stacked mode. Bottom-anchored sliding sheet (drawer) with three snap states (peek 80px, half 45vh, full 92vh) for critical alert triaging.

## Elevation & Depth

Visual hierarchy operates via a strict stack of surface hair-lines, calibrated ambient attenuation, and backdrop filtering rather than deep, murky dropshadows:

- **Level 0 (Basemap / Base Terrain):** Flat `#f8fafc` canvas with vector tiles, contour curves, and vector powerlines.
- **Level 1 (Docked Structural Sidebars):** Pure white (`#ffffff`) background bounded by a `1px` solid border (`#cbd5e1` right/left). No shadow.
- **Level 2 (Floating Spatial Controls & HUD Panels):** Translucent white surface (`rgba(255, 255, 255, 0.92)`), `backdrop-filter: blur(12px)`, bounded by a `1px` border of `#e2e8f0`, backed by an ambient feather shadow: `0 1px 3px rgba(15, 23, 42, 0.05), 0 4px 12px rgba(15, 23, 42, 0.04)`.
- **Level 3 (Context Menus & Feeder Flyouts):** High-density `#ffffff` surface, bounded by `1px solid #cbd5e1`, with crisp spatial shadow: `0 4px 6px -1px rgba(15, 23, 42, 0.08), 0 10px 24px -3px rgba(15, 23, 42, 0.06)`.
- **Level 4 (Critical Modal / Emergency Trip Action):** Center-anchored surface overlay with `0 20px 32px -4px rgba(15, 23, 42, 0.12)`, framed by a definitive hairline of `#94a3b8`.

## Shapes

To sustain an atmosphere of professional technical instrument rigor, this design system operates with **Soft (Level 1)** geometric boundaries:

- **Standard Base Radii:** `0.25rem` (4px) on input fields, buttons, HUD cells, status chips, and table row groupings.
- **Overlay & Sheet Radii:** `0.5rem` (8px) on floating spatial inspector windows, modal dialogues, and context menus.
- **Strict Avoidance:** Pill buttons, circular avatars, and exaggerated corner radii (> 8px) are prohibited. Geometry must reflect industrial calibration tools and mechanical console interfaces.

## Components

### Buttons
- **Primary Operational Button:** Solid Slate 900 background (`#0f172a`), crisp white text (`#ffffff`), `0.25rem` radius, `32px` default height (desktop), `font-size: 13px`, font-weight 500. Focus ring: `2px offset 2px #0284c7`.
- **Secondary Action Button:** White background (`#ffffff`), `1px` solid border (`#cbd5e1`), text `#1e293b`. Hover: background `#f8fafc`, border `#94a3b8`.
- **Emergency Breaker / Critical Action Button:** Background `#dc2626`, text `#ffffff`. Hover: background `#b91c1c`. Active: inset `0 1px 2px rgba(0, 0, 0, 0.2)`.

### Chips & Semantic Telemetry Badges
- **Form Factor:** Compact `20px` height, `4px` corner radius, horizontal padding `6px`, font family `JetBrains Mono`, `11px`, font-weight 500.
- **Normal Status:** Background `#ecfdf5`, border `1px solid #a7f3d0`, text `#065f46`. Prefixed with a static `6px` solid emerald dot.
- **Warning / Solar Throttled:** Background `#fffbeb`, border `1px solid #fde68a`, text `#92400e`.
- **Tripped / Outage:** Background `#fef2f2`, border `1px solid #fecaca`, text `#991b1b`. Includes a micro `1px` outer pulsing radar animation when status is unacknowledged.

### Spatial Inspector Cards
- **Construction:** Grounded in pure white or glassmorphism HUD (`rgba(255, 255, 255, 0.92)`). Outer border `1px solid #e2e8f0`. Header height `36px` with bottom separator `1px solid #f1f5f9`.
- **Data Pairs:** Metric labels displayed in `caption` uppercase Slate 500; primary value directly underneath in `metric-headline` or `metric-label` Slate 900 with units explicitly tagged in Slate 400 (e.g., `412.8` `kV`).

### Data Tables (Feeder Telemetry Stream)
- **Cell Density:** Row height strictly locked to `32px` or `28px` (dense setting). Cell vertical padding `4px`, horizontal padding `8px`.
- **Dividers:** `1px solid #f1f5f9` between rows; column headers locked with bottom border `1px solid #cbd5e1`.
- **Cell Alignment:** Numerical and currency metrics right-aligned with fixed tabular glyph spacing. Text left-aligned. Status icons centered. Hover row highlight: `#f8fafc`.

### Form Controls (Inputs, Selects, Checkboxes)
- **Inputs & Dropdowns:** Pure white background, `1px solid #cbd5e1`, `32px` height, `13px` font size, inner padding `8px`. Hover: border `#94a3b8`. Active/Focus: border `#0284c7` with `3px` light blue halo (`rgba(2, 132, 199, 0.15)`).
- **Checkboxes & Radios:** `14px × 14px` square with `2px` radius. Inactive: `#ffffff` with `1px solid #cbd5e1`. Active: solid `#0f172a` fill containing a crisp 1.5px white checkmark icon.

### Spatial Specific: Map HUD & Layer Switcher
- **Heads-Up Toolbar:** Segmented floating pill bar built with `rgba(255, 255, 255, 0.94)`, `backdrop-filter: blur(8px)`, `1px solid #cbd5e1`. Interactive icons rendered at `16px × 16px` with Slate 700 tone, activating to Slate 900 with a `#e2e8f0` square button background highlight on toggle.