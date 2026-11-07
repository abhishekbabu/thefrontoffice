import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react(), tailwindcss()],
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
