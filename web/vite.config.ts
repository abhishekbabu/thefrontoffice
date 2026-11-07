import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";
import { prePaintScript } from "./src/themes/prepaint";

/** The theme applied before first paint, written into the page from the registry (`src/themes/prepaint.ts`). */
const prePaint = (): Plugin => ({
  name: "pre-paint",
  transformIndexHtml: () => [{ tag: "script", children: prePaintScript(), injectTo: "head" }],
});

export default defineConfig({
  plugins: [react(), tailwindcss(), prePaint()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    // The dev server owns the page; anything under /api is the Python process.
    // Same-origin in production, where FastAPI serves dist/ itself.
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
  // themes.css is read as text by a test of its own; every other stylesheet
  // stays out of the suite, which renders no styles.
  test: { environment: "happy-dom", globals: true, css: { include: [/themes\.css/] } },
});
