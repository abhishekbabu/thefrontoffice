import { describe, expect, it } from "vitest";
import { keys } from "@/lib/queries";
import { ComparisonDrawer } from "@/components/league/compare";
import { offlineClient, render, settle } from "@/test/render";
import { REED_WHITE } from "@/test/players";

const COMPETITION = "nba-yahoo";
const LEAGUE = "L1";

async function opened() {
  const client = offlineClient();

  client.setQueryData(keys.compare(COMPETITION, LEAGUE, ["p.1", "p.2"]), REED_WHITE);

  await render(
    <ComparisonDrawer
      competition={COMPETITION}
      league={LEAGUE}
      comparing={{ ids: ["p.1", "p.2"], title: "Pick up Paul Reed, drop Coby White", tags: { "p.1": "In", "p.2": "Out" } }}
      onClose={() => {}}
      onOpenPlayer={() => {}}
    />,
    client,
  );

  await settle();

  return document.querySelector<HTMLElement>('[role="dialog"]')!;
}

describe("a comparison drawer", () => {
  it("heads the grid with the decision, and says which way each player goes", async () => {
    const dialog = await opened();

    const text = dialog.textContent ?? "";

    expect(dialog.getAttribute("aria-label")).toBe("Compare Paul Reed vs Coby White");
    expect(text).toContain("Pick up Paul Reed, drop Coby White");
    expect(text).toMatch(/InPaul Reed/);
    expect(text).toMatch(/OutCoby White/);
    // A decision's players are not a list to edit.
    expect(dialog.querySelector('[aria-label^="Remove"]')).toBeNull();
  });

  it("carries its players over to the Compare page", async () => {
    window.localStorage.removeItem(`compare:${COMPETITION}:${LEAGUE}`);

    const dialog = await opened();

    dialog.querySelector<HTMLButtonElement>('[aria-label="Open on the Compare page"]')!.click();

    await settle();

    expect(JSON.parse(window.localStorage.getItem(`compare:${COMPETITION}:${LEAGUE}`)!)).toEqual(["p.1", "p.2"]);
  });
});
