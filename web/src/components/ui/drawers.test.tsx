import { describe, expect, it } from "vitest";
import type { Capabilities, Competition, League } from "@/lib/api";
import { keys } from "@/lib/queries";
import type { Comparing } from "@/components/ui/compare";
import { useDrawers } from "@/components/ui/drawers";
import { offlineClient, render, settle } from "@/test/render";
import { REED_WHITE } from "@/test/players";

const NBA = { key: "nba-yahoo" } as Competition;
const LEAGUE = { league_id: "L1" } as League;

function Page({ comparing }: { comparing: Comparing }) {
  const { openComparison, drawer } = useDrawers(NBA, LEAGUE);
  return (
    <>
      <button type="button" onClick={() => openComparison(comparing)}>
        Open
      </button>
      {drawer}
    </>
  );
}

async function page(comparing: Comparing) {
  const client = offlineClient();
  client.setQueryData<Capabilities>(keys.capabilities, { ai: false, limits: { judged: 10 } });
  client.setQueryData(keys.compare(NBA.key, LEAGUE.league_id, ["p.1", "p.2"]), REED_WHITE);
  for (const player of REED_WHITE.players) client.setQueryData(keys.player(NBA.key, LEAGUE.league_id, player.player_id), player);
  const { container } = await render(<Page comparing={comparing} />, client);
  container.querySelector("button")!.click();
  await settle(400);
}

const dialog = () => document.querySelector<HTMLElement>('[role="dialog"]')!;

describe("a page's drawers", () => {
  it("swaps a comparison for one of its players, and his Back link swaps it back", async () => {
    await page({ ids: ["p.1", "p.2"] });
    expect(dialog().getAttribute("aria-label")).toBe("Compare Paul Reed vs Coby White");

    [...dialog().querySelectorAll("button")].find((b) => b.textContent?.includes("Paul Reed"))!.click();
    await settle(400);
    expect(dialog().getAttribute("aria-label")).toBe("Paul Reed");

    [...dialog().querySelectorAll("button")].find((b) => b.textContent?.includes("Compare · Paul Reed vs Coby White"))!.click();
    await settle(400);
    expect(dialog().getAttribute("aria-label")).toBe("Compare Paul Reed vs Coby White");
  });

  it("opens one player alone rather than a comparison of one", async () => {
    await page({ ids: ["p.1"] });
    expect(dialog().getAttribute("aria-label")).toBe("Paul Reed");
  });
});
