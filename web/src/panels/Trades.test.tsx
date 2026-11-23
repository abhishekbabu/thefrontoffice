import { describe, expect, it } from "vitest";
import type { League, TradeIdea, Trades } from "@/lib/types";
import { keys } from "@/lib/queries";
import { priced, theirCase, TradesPanel } from "@/panels/Trades";
import { offlineClient, render } from "@/test/render";
import { competitionOf } from "@/test/leagues";

const idea = (their_playoffs: number, their_points: number, over: Partial<TradeIdea> = {}): TradeIdea => ({
  team_id: "2",
  team: "rival",
  giving: ["A"],
  receiving: ["B"],
  giving_ids: ["a"],
  receiving_ids: ["b"],
  playoffs: 0.9,
  playoffs_change: 0.01,
  their_playoffs_change: 0,
  points: 1,
  their_points,
  playoff_points: 3,
  total: 11,
  their_playoffs,
  pickup: "",
  form: [],
  ...over,
});

describe("why the other manager might take a trade", () => {
  it("is what it is worth, once he is out of the race", () => {
    const said = theirCase(idea(0.01, -2.6));

    expect(said).toContain("1%");
    expect(said).not.toContain("2.6");
  });

  it("is his starters, while he is still chasing a place", () => {
    expect(theirCase(idea(0.4, 1.4))).toContain("+1.4");
  });

  it("is the categories he expects to take, in a category league", () => {
    expect(theirCase(idea(0.01, 0.12), "categories")).toContain("+0.12");
  });
});

describe("a player's pricing", () => {
  it("is found on every trade he is in, under the name the trade lists him by", () => {
    const form = [{ label: "Matthew Golden", value: "priced 18.5", tone: "neutral" as const, url: "", better: null, hint: "" }];

    const ideas = [
      idea(0.4, 1.4, { giving: ["Matthew Golden (WR)"], form }),
      idea(0.4, 1.4, { giving: ["Matthew Golden (WR)", "C (RB)"] }),
    ];

    const pricing = priced(ideas);

    expect(pricing.get("Matthew Golden (WR)")).toBe("priced 18.5");
    expect(pricing.has("C (RB)")).toBe(false);
  });
});

describe("Trades", () => {
  const competition = competitionOf({ key: "nfl-sleeper" });
  const league: League = { league_id: "T1", name: "Sunday Money", detail: "", url: "" };

  async function shown(trades: Trades) {
    const client = offlineClient();

    client.setQueryData(keys.trades(competition.key, league.league_id), trades);

    return render(<TradesPanel competition={competition} league={league} />, client);
  }

  it("names a pickup the trades share once, under the list", async () => {
    const { container } = await shown({
      ideas: [idea(0.4, 1.4), idea(0.4, 1.4, { team_id: "3", receiving: ["C"] })],
      ranked_by: "playoffs_change", measure: "points", deadline: null,
      pickup: "Chig Okonkwo (TE)",
    });

    expect(container.textContent?.split("Chig Okonkwo")).toHaveLength(2);
    expect(container.textContent).not.toContain("deadline");
  });

  it("puts each trade on a row, with the regular season's cost beside the playoff gain it buys", async () => {
    const { container } = await shown({
      ideas: [idea(1, 1.7, { points: -3.0, playoff_points: 2.5, total: -1.5, playoffs_change: -0.003 })],
      ranked_by: "total", measure: "points", deadline: null,
      pickup: "",
    });

    const cells = [...container.querySelectorAll("tbody tr:first-child td")].map((td) => td.textContent);

    expect(cells.slice(0, 2)).toEqual(["A", "B"]);
    expect(cells).toContain("−3.0");
    expect(cells).toContain("+2.5");
    expect(cells).toContain("−1.5");
    // The column the list is ordered by is marked as such.
    expect(container.querySelector('th [aria-label="ordered by"]')?.closest("th")?.textContent).toContain("Total");
  });

  it("counts a category league's figures in categories, and says when trading closes", async () => {
    const { container } = await shown({
      ideas: [idea(0.4, 0.12, { points: 0.07, playoff_points: -0.04, total: 0.92 })],
      ranked_by: "playoffs_change",
      measure: "categories",
      deadline: "2027-02-25",
      pickup: "",
    });

    const headers = [...container.querySelectorAll("thead th")].map((th) => th.textContent);

    expect(headers.some((h) => h?.includes("cats"))).toBe(true);

    const cells = [...container.querySelectorAll("tbody tr:first-child td")].map((td) => td.textContent);

    expect(cells).toContain("+0.07");
    expect(container.textContent).toContain("deadline");
  });

  it("has no playoff column before the playoff weeks are projected", async () => {
    const { container } = await shown({
      ideas: [idea(0.4, 1.4, { playoff_points: null })],
      ranked_by: "playoffs_change", measure: "points", deadline: null,
      pickup: "",
    });

    const headers = [...container.querySelectorAll("thead th")].map((th) => th.textContent);

    expect(headers.some((h) => h?.includes("Playoffs"))).toBe(false);
  });
});
