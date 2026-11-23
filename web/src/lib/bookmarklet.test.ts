/**
 * @vitest-environment-options {"url": "http://yahoo.test/league"}
 *
 * On Yahoo's page, where the bookmark runs: Yahoo's own paths are same-origin,
 * and the app is another origin, answering with the CORS headers it sends.
 * Plain HTTP, because the test DOM calls loopback from an HTTPS page mixed
 * content, which Chrome does not.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { bookmarklet, sync } from "@/lib/bookmarklet";
import { server } from "@/test/server";

const APP = "http://127.0.0.1:8000";
const YAHOO = "http://yahoo.test/";

type Call = { url: string; init?: RequestInit };

/**
 * The app and Yahoo, answered through the real `fetch`: the app plans one step
 * per league it is told of and receipts each league it is handed; Yahoo
 * answers each path from `pages`, an error there being one the network gave.
 */
function world(pages: Record<string, number | "unreachable"> = {}, profile = 200) {
  // Observes what each call asked for (MSW does not see `credentials`); the network still answers.
  const spy = vi.spyOn(globalThis, "fetch");
  const posted: { profile: unknown; responses: { path: string; status: number; body: string }[] }[] = [];

  /** The app's sync routes: a preflight, the plan for a round, and the receipt for what it was handed. */
  async function fromApp(request: Request): Promise<Response> {
    const url = request.url;

    if (request.method === "OPTIONS") return new HttpResponse(null, { status: 204 });

    if (url.startsWith(`${APP}/api/platforms/yahoo/capture/plan`)) {
      const leagues = new URL(url).searchParams.get("leagues")?.split(",").filter(Boolean) ?? [];
      const steps = [{ path: "list", league: "" }, ...leagues.map((key) => ({ path: `league/${key}/settings`, league: key }))];

      return HttpResponse.json({ base: YAHOO, probe: "profile", steps });
    }

    if (url === `${APP}/api/platforms/yahoo/capture`) {
      // SAFETY: the sync posts one capture as JSON, which the assertions on `posted` read back.
      const body = (await request.json()) as (typeof posted)[number];

      posted.push(body);

      const leagues = [...new Set(body.responses.map((r) => r.path.split("/")[1]).filter(Boolean))];

      return HttpResponse.json({ stored: body.responses.length, leagues, errors: [] });
    }

    return new HttpResponse(null, { status: 404 });
  }

  server.use(
    http.all("*", async ({ request }) => {
      const url = request.url;

      if (url.startsWith(APP)) {
        const answer = await fromApp(request);

        for (const [name, value] of cors(request)) answer.headers.set(name, value);

        return answer;
      }

      const path = url.slice(YAHOO.length);

      if (path === "profile") return new HttpResponse("<profile/>", { status: profile });

      if (path === "list") return new HttpResponse("<leagues>466.l.1 466.l.1.t.3 466.l.2</leagues>");

      const answer = pages[path] ?? 200;

      if (answer === "unreachable") return HttpResponse.error();

      return new HttpResponse("<league/>", { status: answer });
    }),
  );

  const calls = (): Call[] =>
    spy.mock.calls.map(([input, init]) => ({ url: input instanceof Request ? input.url : input.toString(), init }));

  return { calls, posted };
}

/** What the app's sync routes send a page of another origin (`capture.py`): its origin allowed, and a preflight's methods. */
function cors(request: Request): [string, string][] {
  return [
    ["access-control-allow-origin", request.headers.get("origin") ?? "*"],
    ["access-control-allow-methods", "GET, POST"],
    ["access-control-allow-headers", "content-type"],
  ];
}

const banner = () => document.querySelector("[role=status]")?.textContent ?? "";

afterEach(() => {
  document.querySelectorAll("[role=status]").forEach((node) => node.remove());

  vi.restoreAllMocks();
});

describe("sync", () => {
  it("stops before fetching anything when Yahoo is signed out, which would otherwise read as no leagues", async () => {
    const { calls, posted } = world({}, 401);

    const said = await sync(APP, fetch, document);

    expect(said).toMatch(/sign in to yahoo/i);
    expect(banner()).toContain(said);
    expect(posted).toEqual([]);
    expect(calls().filter((c) => c.url.startsWith(YAHOO)).map((c) => c.url)).toEqual([`${YAHOO}profile`]);
  });

  it("fetches each round's plan with Yahoo's session, hands over only bodies, and counts the leagues synced", async () => {
    const { calls, posted } = world();

    const said = await sync(APP, fetch, document);

    expect(said).toBe("Synced 2 leagues");
    expect(calls().some((c) => c.url.endsWith("plan?leagues=466.l.1%2C466.l.2"))).toBe(true);

    for (const call of calls()) expect(call.init?.credentials === "include").toBe(call.url.startsWith(YAHOO));

    const handed = posted.flatMap((p) => p.responses);

    expect(handed.map((r) => r.path).sort()).toEqual(["league/466.l.1/settings", "league/466.l.2/settings", "list"]);
    expect(Object.keys(handed[0] ?? {}).sort()).toEqual(["body", "path", "status"]);
    expect(posted.map((p) => p.profile)).toEqual([{ path: "profile", status: 200, body: "" }, { path: "profile", status: 200, body: "" }]);
  });

  it("keeps going past a league whose fetch fails, and says how many failed", async () => {
    const { posted } = world({ "league/466.l.2/settings": "unreachable" });

    const said = await sync(APP, fetch, document);

    expect(said).toMatch(/^Synced 1 league · 1 failed/);
    expect(posted.flatMap((p) => p.responses).map((r) => r.path)).toContain("league/466.l.1/settings");
  });

  it("hands over a response Yahoo refused for the app to report, rather than dropping it", async () => {
    const { posted } = world({ "league/466.l.2/settings": 500 });

    await sync(APP, fetch, document);

    expect(posted.flatMap((p) => p.responses).find((r) => r.path === "league/466.l.2/settings")?.status).toBe(500);
  });

  it("says the app could not be reached rather than failing silently", async () => {
    server.use(http.all("*", () => HttpResponse.error()));

    expect(await sync(APP, fetch, document)).toMatch(/can't reach the app at http:\/\/127\.0\.0\.1:8000/i);
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
    // Evaluated from text on purpose: the bookmark runs as source on Yahoo's
    // page, where nothing this module imports exists.
    // SAFETY: the source is `sync` itself, as `bookmarklet` wraps it.
    // oxlint-disable-next-line typescript/no-implied-eval
    const run = (new Function(`return (${source});`) as () => typeof sync)();

    world();

    expect(await run(APP, fetch, document)).toBe("Synced 2 leagues");
  });
});
