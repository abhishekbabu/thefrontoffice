/**
 * Screenshot every view, so the UI can be looked at rather than reasoned about.
 *
 * Starts the preview server itself and stops it after, so this is one command
 * from a clean shell. Shots land in web/.shots, which is gitignored — they are
 * a way of looking at the app, not an artifact of it.
 *
 * Usage: pnpm shoot [--dark] [--only=landing,week,team,free-agents,league,player,settings]
 */
import { chromium } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const OUT = path.join(ROOT, "web/.shots");
const BASE = "http://127.0.0.1:8100";

const args = process.argv.slice(2);
const dark = args.includes("--dark");
const only = args.find((a) => a.startsWith("--only="))?.slice("--only=".length)?.split(",");

/** Wait for the server to answer rather than sleeping a guessed interval. */
async function waitForServer(timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${BASE}/api/competitions`);
      if (response.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`Preview server never answered on ${BASE}`);
}

/**
 * Refuse to run against a server this script did not start.
 *
 * The spawn below cannot bind a port already in use, so it dies quietly while
 * `waitForServer` succeeds against whatever was already there — and the shots
 * come back from that process's code, not this checkout's.
 */
async function refuseStaleServer() {
  try {
    await fetch(`${BASE}/api/competitions`);
  } catch {
    return; // nothing listening, which is what we want
  }
  throw new Error(
    `Something is already serving ${BASE}. These shots would come from that process, not from your ` +
      `current code. Stop it first:\n\n  pkill -f scripts/preview.py\n`,
  );
}

async function main() {
  await rm(OUT, { recursive: true, force: true });
  await mkdir(OUT, { recursive: true });
  await refuseStaleServer();

  const server = spawn("uv", ["run", "python", "scripts/preview.py"], {
    cwd: ROOT,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const serverLog = [];
  server.stdout.on("data", (d) => serverLog.push(String(d)));
  server.stderr.on("data", (d) => serverLog.push(String(d)));

  const browser = await chromium.launch();
  try {
    await waitForServer();

    const context = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
      deviceScaleFactor: 2,
      colorScheme: dark ? "dark" : "light",
    });
    const page = await context.newPage();

    // Surface anything the app logs; a React error boundary is otherwise
    // invisible in a screenshot that just looks empty.
    const problems = [];
    page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
    page.on("pageerror", (e) => problems.push(String(e)));

    const suffix = dark ? "-dark" : "";
    const shoot = async (name) => {
      await page.waitForTimeout(350); // let queries settle
      await page.screenshot({ path: path.join(OUT, `${name}${suffix}.png`), fullPage: true });
      console.log(`  ${name}${suffix}.png`);
    };

    const wanted = (name) => !only || only.includes(name);

    await page.goto(BASE, { waitUntil: "networkidle" });
    if (wanted("landing")) await shoot("landing");

    // Straight to each view by its address. Driving the rail instead would tie
    // this run to the shape of a control, and break whenever that changes.
    const competitions = await (await fetch(`${BASE}/api/competitions`)).json();
    for (const competition of competitions.filter((c) => c.ready)) {
      const leagues = await (await fetch(`${BASE}/api/${competition.key}/leagues`)).json();
      const league = leagues[0];
      if (!league) continue;

      const name = competition.competition;
      // The long spelling of every view, including the default one. The app
      // rewrites it to the short address on arrival, which is itself worth
      // seeing land correctly.
      const go = async (view) => {
        await page.goto(`${BASE}/${competition.key}/${league.league_id}/${view}`, { waitUntil: "networkidle" });
      };

      if (wanted("week")) {
        await go("week");
        await shoot(`${name}-week`);
      }
      if (wanted("league")) {
        await go("league");
        await page.waitForTimeout(2500); // a whole season of matchups
        await shoot(`${name}-league`);
        // Each tab is a different question; one shot of the first proves
        // nothing about the others.
        for (const tab of ["Table", "Rosters", "Fixtures", "Activity"]) {
          const control = page.getByRole("tab", { name: tab });
          if (await control.count()) {
            await control.click();
            await page.waitForTimeout(400);
            await shoot(`${name}-${tab.toLowerCase()}`);
          }
        }
      }
      if (wanted("free-agents")) {
        await go("free-agents");
        await page.waitForTimeout(2500);
        await shoot(`${name}-free-agents`);
      }
      if (wanted("team")) {
        await go("team");
        await shoot(`${name}-team`);
      }
      if (wanted("player")) {
        await go("team");
        await page.waitForTimeout(500);
        // Open the first row, which is the whole point of the table being one.
        const row = page.locator("tbody tr").first();
        if (await row.count()) {
          await row.click();
          await page.waitForTimeout(700);
          await shoot(`${name}-player`);
        }
      }
    }

    if (wanted("scrolled")) {
      // Deliberately not fullPage: the question is what stays on screen when
      // the content moves, which a full-page capture flattens away.
      await page.goto(`${BASE}/settings`, { waitUntil: "networkidle" });
      await page.waitForTimeout(500);
      await page.mouse.move(900, 500);
      await page.mouse.wheel(0, 1400);
      await page.waitForTimeout(400);
      await page.screenshot({ path: path.join(OUT, `scrolled${suffix}.png`) });
      console.log(`  scrolled${suffix}.png`);
    }

    if (wanted("settings")) {
      await page.goto(`${BASE}/settings`, { waitUntil: "networkidle" });
      await shoot("settings");
    }

    if (problems.length) {
      console.log("\n  Console errors:");
      for (const p of [...new Set(problems)]) console.log(`    ${p}`);
    }
  } catch (error) {
    console.error(`\n  Failed: ${error.message}`);
    console.error(serverLog.join(""));
    process.exitCode = 1;
  } finally {
    await browser.close();
    server.kill("SIGTERM");
  }
}

await main();
