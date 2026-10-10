import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `base: "./"` so the built bundle works wherever it is served from - Cloud
// Run static, Firebase Hosting, or a file path during a backup demo. An
// absolute base breaks the moment the host changes, which is exactly when
// nobody has time to debug it.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    sourcemap: true,
    // No manualChunks: the chart is a dynamic import, so Rollup splits
    // recharts into its own chunk on its own. Declaring one by hand produced
    // an empty `vendor` chunk because recharts pulls React in with it.
  },
  server: { port: 5173, strictPort: true },
});
