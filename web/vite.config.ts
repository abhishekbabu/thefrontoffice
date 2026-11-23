import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";
import { gzipSync } from "node:zlib";
import { prePaintScript } from "./src/themes/prepaint";

/** The theme applied before first paint, written into the page from the registry (`src/themes/prepaint.ts`). */
const prePaint = (): Plugin => ({
  name: "pre-paint",
  transformIndexHtml: () => [{ tag: "script", children: prePaintScript(), injectTo: "head" }],
});

// 150, raised from 140 for react-router: routing is load-bearing for every
// page and belongs in the entry bundle, and the canonical library is worth its
// 10 kB over a smaller one nobody else has to learn.
const BUDGET_KB = 150;

/**
 * Fail the build when what the first paint loads grows past what this app can justify.
 *
 * Everything index.html loads before anything renders — the entry script and
 * every chunk it preloads — is time the page is blank. A budget catches the
 * dependency added for one small thing that brings a library with it, which is
 * invisible in review and shows up months later as "the app got slow".
 * Raise BUDGET_KB deliberately, with the reason in the commit.
 */
const bundleBudget = (): Plugin => ({
  name: "bundle-budget",
  apply: "build",
  writeBundle(_, bundle) {
    const html = Object.values(bundle).find((file) => file.fileName === "index.html");
    const page = html?.type === "asset" ? String(html.source) : "";
    const firstPaint = new Set([...page.matchAll(/(?:src|href)="\/(assets\/[^"]+\.js)"/g)].map((m) => m[1]));
    const kb = (code: string) => gzipSync(code).length / 1024;
    let first = 0;
    let deferred = 0;

    for (const file of Object.values(bundle)) {
      if (file.type !== "chunk") continue;

      if (firstPaint.has(file.fileName)) first += kb(file.code);
      else deferred += kb(file.code);
    }

    if (![...firstPaint].some((f) => f.startsWith("assets/index-"))) this.error("No entry bundle found in index.html.");

    this.info(`first paint ${first.toFixed(1)} kB gzip across ${firstPaint.size} files (budget ${BUDGET_KB}); deferred ${deferred.toFixed(1)} kB`);

    if (first > BUDGET_KB)
      this.error(`Over budget by ${(first - BUDGET_KB).toFixed(1)} kB: defer it behind a dynamic import, or raise BUDGET_KB with the reason.`);
  },
});

/** `PORT` from the environment or the repo's `.env`, as the Python settings read it; 8000 when unset. */
const apiPort = (mode: string): string => loadEnv(mode, fileURLToPath(new URL("..", import.meta.url)), "").PORT || "8000";

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss(), prePaint(), bundleBudget()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    // The dev server owns the page; anything under /api is the Python process.
    // Same-origin in production, where FastAPI serves dist/ itself.
    // The port is the repo's PORT setting (`.env` beside web/), which `just api` listens on.
    proxy: { "/api": { target: `http://127.0.0.1:${apiPort(mode)}`, changeOrigin: true } },
  },
  // themes.css is read as text by a test of its own; every other stylesheet
  // stays out of the suite, which renders no styles.
  test: { environment: "happy-dom", globals: true, css: { include: [/themes\.css/] } },
}));
