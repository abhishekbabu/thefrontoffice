import { afterEach, describe, expect, it } from "vitest";
import { bookmarklet, sync } from "@/lib/bookmarklet";

const APP = "http://127.0.0.1:8000";
const YAHOO = "https://yahoo.test/";

type Call = { url: string; init?: RequestInit };

/**
 * The app and Yahoo, standing in: the app plans one step per league it is told
 * of and receipts each league it is handed; Yahoo answers each path from `pages`.
 */
function world(pages: Record<string, number | Error> = {}, profile = 200) {
  const calls: Call[] = [];
  const posted: { profile: unknown; responses: { path: string; status: number; body: string }[] }[] = [];
  const http = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    if (url.startsWith(`${APP}/api/yahoo/capture/plan`)) {
      const leagues = new URL(url).searchParams.get("leagues")?.split(",").filter(Boolean) ?? [];
      const steps = [{ path: "list", league: "" }, ...leagues.map((key) => ({ path: `league/${key}/settings`, league: key }))];
      return Response.json({ base: YAHOO, probe: "profile", steps });
    }
    if (url === `${APP}/api/yahoo/capture`) {
      const body = JSON.parse(String(init?.body));
      posted.push(body);
      const leagues = [...new Set(body.responses.map((r: { path: string }) => r.path.split("/")[1]).filter(Boolean))];
      return Response.json({ stored: body.responses.length, leagues, errors: [] });
    }
    const path = url.slice(YAHOO.length);
    if (path === "profile") return new Response("<profile/>", { status: profile });
    if (path === "list") return new Response("<leagues>466.l.1 466.l.1.t.3 466.l.2</leagues>");
    const answer = pages[path] ?? 200;
    if (answer instanceof Error) throw answer;
    return new Response("<league/>", { status: answer });
  }) as typeof fetch;
  return { http, calls, posted };
}

const banner = () => document.querySelector("[role=status]")?.textContent ?? "";

afterEach(() => document.querySelectorAll("[role=status]").forEach((node) => node.remove()));

describe("sync", () => {
  it("stops before fetching anything when Yahoo is signed out, which would otherwise read as no leagues", async () => {
    const { http, calls, posted } = world({}, 401);

    const said = await sync(APP, http, document);

    expect(said).toMatch(/sign in to yahoo/i);
    expect(banner()).toContain(said);
    expect(posted).toEqual([]);
    expect(calls.filter((c) => c.url.startsWith(YAHOO)).map((c) => c.url)).toEqual([`${YAHOO}profile`]);
  });

  it("fetches each round's plan with Yahoo's session, hands over only bodies, and counts the leagues synced", async () => {
    const { http, calls, posted } = world();

    const said = await sync(APP, http, document);

    expect(said).toBe("Synced 2 leagues");
    expect(calls.some((c) => c.url.endsWith("plan?leagues=466.l.1%2C466.l.2"))).toBe(true);
    for (const call of calls) expect(call.init?.credentials === "include").toBe(call.url.startsWith(YAHOO));
    const handed = posted.flatMap((p) => p.responses);
    expect(handed.map((r) => r.path).sort()).toEqual(["league/466.l.1/settings", "league/466.l.2/settings", "list"]);
    expect(Object.keys(handed[0] ?? {}).sort()).toEqual(["body", "path", "status"]);
    expect(posted.map((p) => p.profile)).toEqual([{ path: "profile", status: 200, body: "" }, { path: "profile", status: 200, body: "" }]);
  });

  it("keeps going past a league whose fetch fails, and says how many failed", async () => {
    const { http, posted } = world({ "league/466.l.2/settings": new Error("blocked") });

    const said = await sync(APP, http, document);

    expect(said).toMatch(/^Synced 1 league · 1 failed/);
    expect(posted.flatMap((p) => p.responses).map((r) => r.path)).toContain("league/466.l.1/settings");
  });

  it("hands over a response Yahoo refused for the app to report, rather than dropping it", async () => {
    const { http, posted } = world({ "league/466.l.2/settings": 500 });

    await sync(APP, http, document);

    expect(posted.flatMap((p) => p.responses).find((r) => r.path === "league/466.l.2/settings")?.status).toBe(500);
  });

  it("says the app could not be reached rather than failing silently", async () => {
    const http = (async () => {
      throw new TypeError("Failed to fetch");
    }) as typeof fetch;

    expect(await sync(APP, http, document)).toMatch(/can't reach the app at http:\/\/127\.0\.0\.1:8000/i);
  });
});

describe("bookmarklet", () => {
  it("is a javascript: link that runs the sync against the app it was served from", () => {
    const href = bookmarklet(APP);

    expect(href.startsWith("javascript:")).toBe(true);
    const code = decodeURIComponent(href.slice("javascript:".length));
    expect(code.startsWith("void (")).toBe(true);
    expect(code).toContain(`(${JSON.stringify(APP)})`);
  });

  it("carries a sync that runs from its source text alone, closing over nothing", async () => {
    const code = decodeURIComponent(bookmarklet(APP).slice("javascript:".length));
    const source = code.slice("void (".length, code.lastIndexOf(`)(${JSON.stringify(APP)})`));
    const run = new Function(`return (${source});`)() as typeof sync;

    expect(await run(APP, world().http, document)).toBe("Synced 2 leagues");
  });
});
