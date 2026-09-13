import { Component } from "react";

/**
 * The last line of the same defence `dataSource` provides for the API.
 *
 * `vite.config.js` splits maplibre and recharts out of the entry chunk and says
 * of the result screen: "if the map chunk fails to load, the result still
 * renders." Without a boundary that was not true — React unmounts the whole
 * tree on a render or lazy-import failure, and a chunk that 404s on a flaky
 * connection took the entire application down to a white page. Which is the
 * exact failure ARCHITECTURE.md 9.3 exists to prevent, arriving by a different
 * road.
 *
 * `quiet` is for decorative subtrees — the spatial canvas — where the honest
 * degradation is to render nothing and let the numbers carry the screen.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    // Console only. There is no telemetry endpoint in Phase 1 and adding one
    // would ship a household's session somewhere ARCHITECTURE.md 8 does not
    // sanction.
    console.error("[pvmaps] render failed:", error);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    if (this.props.quiet) return this.props.fallback ?? null;

    return (
      <div className="p-4">
        <div className="notice notice-critical">
          <p className="font-medium">Something on this screen failed to load</p>
          <p className="mt-1 leading-[18px]">
            Nothing was sent anywhere and nothing was saved. Reload the page and
            run the address again.
          </p>
          <a href="/" className="btn mt-3">
            Start again
          </a>
        </div>
      </div>
    );
  }
}
