import { describe, expect, it } from "vitest";
import type { CaptureStatus } from "@/lib/api";
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
    const { container } = await settingsWith({ active: true, synced_at: null, leagues: [] });
    const link = [...container.querySelectorAll("a")].find((a) => a.textContent === "Sync Yahoo");

    const href = link?.getAttribute("href") ?? "";
    expect(href.startsWith("javascript:")).toBe(true);
    expect(decodeURIComponent(href)).toContain(JSON.stringify(window.location.origin));
  });

  it("says it has never run before the first sync", async () => {
    const { card } = await settingsWith({ active: true, synced_at: null, leagues: [] });
    expect(card).toContain("Never synced");
  });

  it("says when it last ran, and which leagues it holds", async () => {
    const synced = new Date();
    synced.setHours(9, 5);
    const { card } = await settingsWith({ active: true, synced_at: synced.toISOString(), leagues: ["Hoops", "Dunks"] });

    expect(card).toMatch(/Last synced 0?9:05/);
    expect(card).toContain("Hoops · Dunks");
    expect(card).not.toContain("YAHOO_SOURCE");
  });

  it("says the sync is not read while Yahoo is read through OAuth", async () => {
    const { card } = await settingsWith({ active: false, synced_at: null, leagues: [] });
    expect(card).toContain("YAHOO_SOURCE");
  });
});
