import { act } from "react";
import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import type { CaptureStatus, Setting, SettingsGroup } from "@/lib/types";
import { keys } from "@/lib/queries";
import { SettingsPanel } from "@/panels/Settings";
import { offlineClient, render } from "@/test/render";

const group = (title: string, section: SettingsGroup["section"], platform = "", settings: Setting[] = []): SettingsGroup => ({
  title,
  note: "",
  section,
  platform,
  switch: "",
  modes: {},
  settings,
});

const YAHOO = group("NBA on Yahoo", "platforms", "yahoo");
const YAHOO_CARD = '[role=group][aria-label="NBA on Yahoo"]';

async function settingsWith(status: CaptureStatus, groups: SettingsGroup[] = [YAHOO]) {
  const client = offlineClient();

  client.setQueryData(keys.settings, groups);

  client.setQueryData(keys.capture("yahoo"), status);

  const { container } = await render(<SettingsPanel onBack={() => {}} />, client);

  const card = container.querySelector(YAHOO_CARD);

  return { container, card: card?.textContent ?? "" };
}

describe("Yahoo status", () => {
  it("is not shown without a Yahoo group", async () => {
    const { container } = await settingsWith({ active: true, synced_at: null, leagues: [], session: null }, []);

    expect(container.textContent).not.toContain("Sync Yahoo");
  });

  it("offers the bookmark, built to call back the app it is served from", async () => {
    const { container } = await settingsWith({ active: true, synced_at: null, leagues: [], session: null });

    const link = [...container.querySelectorAll("a")].find((a) => a.textContent === "Sync Yahoo");

    const href = link?.getAttribute("href") ?? "";

    expect(href.startsWith("javascript:")).toBe(true);
    expect(decodeURIComponent(href)).toContain(JSON.stringify(window.location.origin));
  });

  it("says it has never run before the first sync", async () => {
    const { card } = await settingsWith({ active: true, synced_at: null, leagues: [], session: null });

    expect(card).toContain("Never synced");
  });

  it("says when it last ran, and how many leagues it holds, in its status", async () => {
    const synced = new Date();

    synced.setHours(9, 5);

    const { card } = await settingsWith({
      active: true,
      synced_at: synced.toISOString(),
      leagues: ["Hoops", "Dunks"],
      session: null,
    });

    expect(card).toMatch(/2 leagues · last synced 0?9:05/);
    expect(card).not.toContain("Hoops");
  });

  it("says how to copy the session cookie, and where it goes, while read with one", async () => {
    const { card } = await settingsWith({ active: false, synced_at: null, leagues: [], session: { fetched_at: null, expired: false } });

    expect(card).toContain("pub-api-ro.fantasysports.yahoo.com");
    expect(card).toContain("YAHOO_SESSION_COOKIE");
  });

  it("read with the session, says when it last fetched", async () => {
    const fetched = new Date();

    fetched.setHours(9, 5);

    const { card } = await settingsWith({
      active: false,
      synced_at: null,
      leagues: [],
      session: { fetched_at: fetched.toISOString(), expired: false },
    });

    expect(card).toMatch(/Last fetched 0?9:05/);
  });

  it("read with the session, says it expired in words", async () => {
    const { card } = await settingsWith({
      active: false,
      synced_at: null,
      leagues: [],
      session: { fetched_at: null, expired: true },
    });

    expect(card).toContain("Session expired");
  });
});

function setting(key: string, kind: Setting["kind"], value: string, choices: string[] = [], mode = ""): Setting {
  return {
    key,
    field: key.toLowerCase(),
    secret: false,
    present: true,
    kind,
    choices,
    value,
    shadowed: false,
    effective: value,
    mode,
    hint: "",
  };
}

const GROUPS: SettingsGroup[] = [
  group("NBA on Yahoo", "platforms", "yahoo", [
    setting("YAHOO_SOURCE", "choice", "oauth", ["oauth", "browser", "session"]),
    setting("LOG_LEVEL", "choice", "INFO", ["DEBUG", "INFO", "WARNING"]),
    setting("DEBUG_MODE", "boolean", "false"),
  ]),
];

/** Settings with the fixed-value fields, and every PUT the page sends recorded. */
async function fixedValues() {
  const saved: Record<string, string>[] = [];
  const capture: CaptureStatus = { active: false, synced_at: null, leagues: [], session: null };

  server.use(
    http.all("*", async ({ request }) => {
      if (request.method === "PUT") {
        // SAFETY: the settings page PUTs `{ values }`, which the assertions on `saved` read back.
        saved.push(((await request.json()) as { values: Record<string, string> }).values);
      }

      return HttpResponse.json(new URL(request.url).pathname.endsWith("/capture") ? capture : GROUPS);
    }),
  );

  const client = offlineClient();

  client.setQueryData(keys.settings, GROUPS);

  client.setQueryData(keys.capture("yahoo"), capture);

  const { container } = await render(<SettingsPanel onBack={() => {}} />, client);

  const group = (key: string) => container.querySelector<HTMLElement>(`[role=group][aria-label="${key}"]`)!;
  const chips = (key: string) => [...group(key).querySelectorAll<HTMLButtonElement>("button[aria-pressed]")];
  const pressed = (key: string) => chips(key).filter((c) => c.getAttribute("aria-pressed") === "true").map((c) => c.textContent);
  const chip = (key: string, text: string) => chips(key).find((c) => c.textContent === text)!;
  const click = (el: HTMLElement) => act(async () => el.click());
  const save = () => container.querySelector<HTMLButtonElement>("button[aria-label^=Save]");
  const discard = () => container.querySelector<HTMLButtonElement>("button[aria-label^=Discard]");
  const status = () => container.querySelector("[role=status]")?.textContent;

  return { container, saved, chips, pressed, chip, click, save, discard, status };
}

describe("Fixed-value settings", () => {
  it("offers each choice as a chip, with the stored one pressed", async () => {
    const { chips, pressed } = await fixedValues();

    expect(chips("LOG_LEVEL").map((c) => c.textContent)).toEqual(["DEBUG", "INFO", "WARNING"]);
    expect(pressed("LOG_LEVEL")).toEqual(["INFO"]);
    expect(pressed("YAHOO_SOURCE")).toEqual(["oauth"]);
    expect(chips("DEBUG_MODE")).toHaveLength(2);
  });

  it("saves the pressed choice, and a boolean as .env spells it", async () => {
    const { saved, pressed, chip, chips, click, save } = await fixedValues();

    await click(chip("YAHOO_SOURCE", "browser"));

    await click(chips("DEBUG_MODE").find((c) => c.getAttribute("aria-pressed") === "false")!);

    expect(pressed("YAHOO_SOURCE")).toEqual(["browser"]);

    await click(save()!);

    expect(saved).toEqual([{ YAHOO_SOURCE: "browser", DEBUG_MODE: "true" }]);
  });

  it("has nothing to save once a choice is pressed back to the stored one", async () => {
    const { chip, click, save } = await fixedValues();

    await click(chip("LOG_LEVEL", "DEBUG"));

    expect(save()?.disabled).toBe(false);

    await click(chip("LOG_LEVEL", "INFO"));

    expect(save()).toBeNull();
  });
});

describe("Saving", () => {
  it("says how many changes wait, and that they were saved", async () => {
    const { chip, click, save, status } = await fixedValues();

    await click(chip("LOG_LEVEL", "DEBUG"));

    expect(status()).toBe("1 unsaved");

    await click(save()!);

    await vi.waitFor(() => expect(status()).toBe("Saved"));
  });

  it("discards every unsaved change at once", async () => {
    const { chip, click, discard, pressed, saved, status } = await fixedValues();

    await click(chip("LOG_LEVEL", "DEBUG"));

    await click(chip("YAHOO_SOURCE", "session"));

    await click(discard()!);

    expect(pressed("LOG_LEVEL")).toEqual(["INFO"]);
    expect(pressed("YAHOO_SOURCE")).toEqual(["oauth"]);
    expect(status()).toBe("");
    expect(discard()).toBeNull();
    expect(saved).toEqual([]);
  });
});

describe("Layout", () => {
  it("runs from the accounts read to what is rarely touched", async () => {
    const { container } = await settingsWith({ active: false, synced_at: null, leagues: [], session: null }, [
      YAHOO,
      group("Model providers", "ai"),
      group("Tracing", "advanced"),
    ]);

    expect([...container.querySelectorAll("h2")].map((h) => h.textContent)).toEqual([
      "Platforms",
      "AI",
      "Appearance",
      "Advanced",
    ]);
  });
});

describe("A group read more than one way", () => {
  const SWITCHED: SettingsGroup = {
    ...group("NBA on Yahoo", "platforms", "yahoo", [
      setting("YAHOO_SOURCE", "choice", "session", ["oauth", "browser", "session"]),
      setting("YAHOO_SESSION_COOKIE", "text", "", [], "session"),
      setting("YAHOO_CLIENT_ID", "text", "", [], "oauth"),
      { ...setting("YAHOO_MAX_WEEKLY_ADDS", "integer", "3"), hint: "fallback only" },
    ]),
    switch: "YAHOO_SOURCE",
    modes: { oauth: "needs a developer app", browser: "run the bookmark", session: "reads your cookie" },
  };

  const session = { active: false, synced_at: null, leagues: [], session: { fetched_at: null, expired: false } };

  async function switched() {
    const { container } = await settingsWith(session, [SWITCHED]);

    const card = container.querySelector<HTMLElement>(YAHOO_CARD)!;
    const other = () => [...card.querySelectorAll("details")].find((d) => d.textContent?.startsWith("Other methods"));
    const shown = (key: string) => [...card.querySelectorAll("code")].some((c) => c.textContent === key && !other()?.contains(c));

    const chip = (text: string) =>
      [...card.querySelectorAll<HTMLButtonElement>("[aria-label=YAHOO_SOURCE] button")].find((c) => c.textContent === text)!;

    return { card, other, shown, chip };
  }

  it("spells out only the way chosen, and folds the others' fields away", async () => {
    const { card, other, shown } = await switched();

    expect(card.textContent).toContain("reads your cookie");
    expect(card.textContent).not.toContain("needs a developer app");
    expect(shown("YAHOO_SESSION_COOKIE")).toBe(true);
    expect(shown("YAHOO_CLIENT_ID")).toBe(false);
    expect(other()?.textContent).toContain("YAHOO_CLIENT_ID");
  });

  it("shows what a way needs as soon as it is pressed, before it is saved", async () => {
    const { card, chip, other, shown } = await switched();

    await act(async () => chip("oauth").click());

    expect(card.textContent).toContain("needs a developer app");
    expect(shown("YAHOO_CLIENT_ID")).toBe(true);
    expect(other()?.textContent).toContain("YAHOO_SESSION_COOKIE");
  });

  it("says what a setting does where it carries a hint", async () => {
    const { card } = await switched();

    expect(card.textContent).toContain("fallback only");
  });
});
