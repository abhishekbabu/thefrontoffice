import { describe, expect, it, vi } from "vitest";
import { keys } from "@/lib/queries";
import { ComparisonDrawer, compareLabel, sides, traded, type Comparing } from "@/components/ui/compare";
import type { TradeIdea } from "@/lib/api";
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

describe("what a comparison is called", () => {
  it("names each side where it has sides, rather than each player against each", () => {
    expect(sides(REED_WHITE, { "p.1": "Get", "p.2": "Give" })).toBe("Get Paul Reed · Give Coby White");
    expect(sides(REED_WHITE, { "p.1": "Give", "p.2": "Give" })).toBe("Give Paul Reed, Coby White");
    expect(sides(REED_WHITE, undefined)).toBe("");
  });

  it("is its players' names, or the fallback before they load", () => {
    expect(compareLabel(REED_WHITE)).toBe("Paul Reed vs Coby White");
    expect(compareLabel(undefined, "Players")).toBe("Players");
  });
});

const idea = (over: Partial<TradeIdea>): TradeIdea => ({
  team_id: "2",
  team: "Rival",
  giving: ["A"],
  receiving: ["B"],
  giving_ids: ["a"],
  receiving_ids: ["b"],
  playoffs: 0.9,
  playoffs_change: 0.01,
  their_playoffs_change: 0,
  points: 1,
  their_points: 1,
  playoff_points: 3,
  total: 11,
  their_playoffs: 0.5,
  pickup: "",
  form: [],
  ...over,
});

describe("what a trade opens", () => {
  it("both sides side by side, what you give first, each column saying which", () => {
    const onCompare = vi.fn<(comparing: Comparing) => void>();

    traded(idea({ giving_ids: ["a1", "a2"], receiving_ids: ["b"] }), onCompare)!();

    expect(onCompare).toHaveBeenCalledWith({
      ids: ["a1", "a2", "b"],
      title: "Trade with Rival",
      tags: { a1: "Give", a2: "Give", b: "Get" },
    });
  });

  it("nothing where the trade carries no players to open", () => {
    expect(traded(idea({ giving_ids: [], receiving_ids: [] }), vi.fn<(comparing: Comparing) => void>())).toBeUndefined();
  });
});
