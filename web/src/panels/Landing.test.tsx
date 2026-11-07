import { describe, expect, it, vi } from "vitest";
import type { Competition, League } from "@/lib/api";
import { keys } from "@/lib/queries";
import { Landing } from "@/panels/Landing";
import { offlineClient, render } from "@/test/render";

// Only what the landing page reads; the rest of a competition is other pages' business.
const NFL = { key: "nfl-sleeper", label: "NFL", configured: true, ready: true } as Competition;
const LEAGUE: League = { league_id: "900", name: "Work League", detail: "3 of 12", url: "https://sleeper.example/900" };

async function landing(onPick = vi.fn()) {
  const client = offlineClient();
  client.setQueryData(keys.leagues(NFL.key), [LEAGUE]);
  const { container } = await render(<Landing competitions={[NFL]} onPick={onPick} />, client);
  return container;
}

describe("the landing page", () => {
  it("never puts the link to the platform inside the button that opens the league", async () => {
    const page = await landing();

    expect(page.querySelector("a[href]")?.getAttribute("href")).toBe(LEAGUE.url);
    expect(page.querySelector("button a, a button")).toBeNull();
  });

  it("opens the league from its row", async () => {
    const onPick = vi.fn();
    const page = await landing(onPick);

    page.querySelector<HTMLButtonElement>("button")!.click();

    expect(onPick).toHaveBeenCalledWith(NFL, LEAGUE);
  });
});
