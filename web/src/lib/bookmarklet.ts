/**
 * The Yahoo sync bookmark: a script run on a Yahoo Fantasy page that fetches
 * what the app needs with the session that page already has, and hands the
 * response bodies to the app.
 *
 * Yahoo's API refuses the app until Yahoo reviews it, but Yahoo's own pages
 * read the same data from a read-only host with their cookie. The script knows
 * nothing of what the app reads: it asks the app for a plan, fetches it, hands
 * it over and asks again until the plan holds nothing new. Cookies never leave
 * the page — the browser attaches them to Yahoo's requests and to nothing else.
 *
 * `sync` is put in the bookmark as its source text, like `prePaint`, so it
 * closes over nothing and imports nothing.
 */

/** Where Settings serves the bookmark from, so the bookmark calls back the same app. */
export function bookmarklet(app: string): string {
  return "javascript:" + encodeURIComponent(`void (${sync.toString()})(${JSON.stringify(app)});`);
}

type Step = { path: string; league: string };
type Plan = { base: string; probe: string; steps: Step[] };
type Receipt = { stored: number; leagues: string[]; errors: string[] };

/**
 * One sync, reported in a small banner on the page; resolves to what it said last.
 *
 * Each response is fetched on its own, so one that fails costs that response
 * and its league's completeness, never the rest. Two at a time, as the server
 * reads the same host with a cookie: Yahoo's own page is still running beside
 * it, and every request is the person's own.
 */
export async function sync(app: string, http: typeof fetch = fetch, page: Document = document): Promise<string> {
  const endpoint = `${app}/api/platforms/yahoo/capture`;
  const banner = page.createElement("div");
  banner.setAttribute("role", "status");
  // Inline, and in fixed colors: this lands on Yahoo's page, where the app's tokens do not exist.
  banner.style.cssText =
    "position:fixed;top:12px;right:12px;z-index:2147483647;max-width:360px;padding:10px 14px;" +
    "border-radius:8px;background:#171717;color:#ededed;font:13px/1.4 system-ui,sans-serif;" +
    "box-shadow:0 4px 16px rgba(0,0,0,.3);cursor:pointer";
  banner.title = "Dismiss";
  banner.onclick = () => banner.remove();
  page.body.append(banner);
  const say = (text: string) => {
    banner.textContent = `Front Office · ${text}`;
    return text;
  };

  const ask = async <T>(path: string, init?: RequestInit): Promise<T> => {
    let response: Response;
    try {
      response = await http(path, init);
    } catch {
      throw new Error(`Can't reach the app at ${app}. Is it running, and was local network access allowed?`);
    }
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    if (!response.ok) throw new Error(body.detail || `The app answered ${response.status}.`);
    return body as T;
  };

  try {
    say("Syncing Yahoo…");
    let plan = await ask<Plan>(`${endpoint}/plan`);
    // Signed out, Yahoo answers its lists empty rather than refusing them,
    // which would read as having no leagues. Its profile does refuse.
    const probe = await http(plan.base + plan.probe, { credentials: "include" });
    if (probe.status !== 200) {
      throw new Error(probe.status === 401 ? "Sign in to Yahoo, then click the bookmark again." : `Yahoo answered ${probe.status}.`);
    }
    const profile = { path: plan.probe, status: probe.status, body: "" };

    const fetched = new Set<string>();
    const leagues = new Set<string>();
    const synced = new Set<string>();
    const errors: string[] = [];
    for (let round = 0; round < 6; round++) {
      if (round) plan = await ask<Plan>(`${endpoint}/plan?leagues=${encodeURIComponent([...leagues].join(","))}`);
      const todo = plan.steps.filter((step) => !fetched.has(step.path));
      if (!todo.length) break;
      todo.forEach((step) => fetched.add(step.path));

      const responses: { path: string; status: number; body: string }[] = [];
      let next = 0;
      let done = fetched.size - todo.length;
      const worker = async () => {
        for (let step = todo[next++]; step; step = todo[next++]) {
          try {
            const response = await http(plan.base + step.path, { credentials: "include" });
            const body = await response.text();
            responses.push({ path: step.path, status: response.status, body });
            // League keys only, read off the account's lists: the plan says the rest.
            if (!step.league) (body.match(/\d+\.l\.\d+/g) ?? []).forEach((key) => leagues.add(key));
          } catch (e) {
            errors.push(`${step.league || "account"} ${step.path}: ${e instanceof Error ? e.message : String(e)}`);
          }
          say(`Fetched ${++done} of ${fetched.size}…`);
        }
      };
      await Promise.all([worker(), worker()]);

      const receipt = await ask<Receipt>(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile, responses }),
      });
      receipt.leagues.forEach((key) => synced.add(key));
      errors.push(...receipt.errors);
    }

    if (errors.length) console.warn("Front Office sync:", errors);
    const failed = errors.length ? ` · ${errors.length} failed (see console)` : "";
    return say(`Synced ${synced.size} league${synced.size === 1 ? "" : "s"}${failed}`);
  } catch (e) {
    return say(`Sync failed: ${e instanceof Error ? e.message : String(e)}`);
  }
}
