import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CaptureStatus, Setting, SettingsGroup } from "@/lib/api";
import { keys } from "@/lib/queries";
import { SettingsPanel } from "@/panels/Settings";
import { offlineClient, render } from "@/test/render";

async function settingsWith(status: CaptureStatus) {
  const client = offlineClient();
  client.setQueryData(keys.settings, []);
  client.setQueryData(keys.capture("yahoo"), status);
  const { container } = await render(<SettingsPanel onBack={() => {}} />, client);
  const card = [...container.querySelectorAll("div")].find((d) => d.textContent?.startsWith("Yahoo sync"));
  return { container, card: card?.textContent ?? "" };
}

describe("Yahoo sync", () => {
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

  it("says when it last ran, and which leagues it holds", async () => {
    const synced = new Date();
    synced.setHours(9, 5);
    const { card } = await settingsWith({ active: true, synced_at: synced.toISOString(), leagues: ["Hoops", "Dunks"], session: null });

    expect(card).toMatch(/Last synced 0?9:05/);
    expect(card).toContain("Hoops · Dunks");
    expect(card).not.toContain("is oauth");
  });

  it("says the sync is not read while Yahoo is read through OAuth", async () => {
    const { card } = await settingsWith({ active: false, synced_at: null, leagues: [], session: null });
    expect(card).toContain("is oauth");
  });

  it("says how to copy the session cookie, and where it goes", async () => {
    const { card } = await settingsWith({ active: false, synced_at: null, leagues: [], session: null });
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
    expect(card).not.toContain("is oauth");
  });

  it("read with the session, says it expired in words", async () => {
    const { card } = await settingsWith({
      active: false,
      synced_at: null,
      leagues: [],
      session: { fetched_at: null, expired: true },
    });

    expect(card).toContain("Session expired");
    expect(card).toContain("Paste a fresh one");
  });
});

function setting(key: string, kind: Setting["kind"], value: string, choices: string[] = []): Setting {
  return { key, field: key.toLowerCase(), secret: false, present: true, kind, choices, value, shadowed: false, effective: value };
}

const GROUPS: SettingsGroup[] = [
  {
    title: "General",
    note: "",
    settings: [
      setting("YAHOO_SOURCE", "choice", "oauth", ["oauth", "browser", "session"]),
      setting("LOG_LEVEL", "choice", "INFO", ["DEBUG", "INFO", "WARNING"]),
      setting("DEBUG_MODE", "boolean", "false"),
    ],
  },
];

/** Settings with the fixed-value fields, and every PUT the page sends recorded. */
async function fixedValues() {
  const saved: Record<string, string>[] = [];
  const capture: CaptureStatus = { active: false, synced_at: null, leagues: [], session: null };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "PUT") saved.push((JSON.parse(String(init.body)) as { values: Record<string, string> }).values);
      return Response.json(path.endsWith("/capture") ? capture : GROUPS);
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
  return { saved, chips, pressed, chip, click, save };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

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
