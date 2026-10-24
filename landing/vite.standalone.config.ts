import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

// Builds the landing page into one self-contained HTML file: dist-standalone/standalone.html
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: "dist-standalone",
    rollupOptions: { input: "standalone.html" },
  },
});
