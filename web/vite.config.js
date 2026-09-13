import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  build: {
    outDir: "dist",
    sourcemap: true,
    rollupOptions: {
      output: {
        // ARCHITECTURE.md 10 builds the result screen (item 5) BEFORE the map
        // (item 6). Keeping maplibre and recharts out of the entry chunk means
        // the result path does not pay to download a map it may never show --
        // and if the map chunk fails to load, the result still renders.
        manualChunks: {
          maplibre: ["maplibre-gl"],
          charts: ["recharts"],
        },
      },
    },
  },
});
