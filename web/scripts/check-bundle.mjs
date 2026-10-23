/**
 * Fail the build when what the first paint loads grows past what this app can justify.
 *
 * Everything here is loaded before anything renders, so its size is time the
 * page is blank. A budget catches the case a dependency is added for one small
 * thing and brings a library with it — which is invisible in review and shows
 * up months later as "the app got slow".
 *
 * Raise BUDGET deliberately, with the reason in the commit.
 */
import { gzipSync } from "node:zlib";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DIST = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../dist/assets");
// 150, raised from 140 for react-router: routing is load-bearing for every
// page and belongs in the entry bundle, and the canonical library is worth its
// 10 kB over a smaller one nobody else has to learn.
const BUDGET_KB = 150;

const files = await readdir(DIST);
const html = await readFile(path.join(DIST, "..", "index.html"), "utf8");

// Everything index.html loads before anything renders: the entry script and
// every chunk it preloads. Counting the entry file alone stopped meaning
// anything once the bundler began splitting shared code into preloaded chunks —
// those load at first paint just the same, and a budget that misses them
// passes a page that is slower than it says.
const firstPaint = [...html.matchAll(/(?:src|href)="\/assets\/([^"]+\.js)"/g)].map((m) => m[1]);
if (!firstPaint.some((f) => f.startsWith("index-"))) {
  console.error("  No entry bundle found. Did the build run?");
  process.exit(1);
}

const size = async (f) => gzipSync(await readFile(path.join(DIST, f))).length / 1024;
const gzipped = (await Promise.all(firstPaint.map(size))).reduce((total, kb) => total + kb, 0);
const deferred = (
  await Promise.all(files.filter((f) => f.endsWith(".js") && !firstPaint.includes(f)).map(size))
).reduce((total, kb) => total + kb, 0);

console.log(`  first paint ${gzipped.toFixed(1)} kB gzip across ${firstPaint.length} files (budget ${BUDGET_KB})`);
if (deferred) console.log(`  deferred ${deferred.toFixed(1)} kB gzip, loaded after first paint`);

if (gzipped > BUDGET_KB) {
  console.error(`\n  Over budget by ${(gzipped - BUDGET_KB).toFixed(1)} kB.`);
  console.error("  Either defer it behind a dynamic import, or raise BUDGET with the reason.");
  process.exit(1);
}
