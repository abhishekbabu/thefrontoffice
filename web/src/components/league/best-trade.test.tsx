import { describe, expect, it } from "vitest";
import type { TradeIdea, Trades } from "@/lib/types";
import { keys } from "@/lib/queries";
import { offlineClient, render } from "@/test/render";
import { BestTrade, gain } from "@/components/league/best-trade";
import { competitionOf, leagueOf } from "@/test/leagues";

describe("the best trade under the deadline item", () => {
  const competition = competitionOf({ key: "nfl-sleeper" });
  const league = leagueOf("T1");

  const idea: TradeIdea = {
    team_id: "2",
    team: "Rival",
    giving: ["Puka Nacua"],
    receiving: ["Bijan Robinson"],
    giving_ids: ["4983"],
    receiving_ids: ["9509"],
    playoffs: 0.9,
    playoffs_change: 0.02,
    their_playoffs_change: 0,
    points: 1,
    their_points: 1,
    playoff_points: 3.2,
    total: 12.4,
    their_playoffs: 0.4,
    pickup: "",
    form: [],
  };

  async function shown(trades: Trades) {
    const client = offlineClient();

    client.setQueryData(keys.trades(competition.key, league.league_id), trades);

    return (await render(<BestTrade competition={competition} league={league} />, client)).container;
  }

  it("names the Trades page's first offer, who to make it to and what it gains, with a way there", async () => {
    const container = await shown({ ideas: [idea, { ...idea, team: "Other" }], ranked_by: "total", measure: "points", deadline: null, pickup: "" });

    expect(container.textContent).toContain("Puka Nacua");
    expect(container.textContent).toContain("Bijan Robinson");
    expect(container.textContent).toContain("Rival");
    expect(container.textContent).not.toContain("Other");
    expect(container.textContent).toContain("+12.4");
    expect(container.querySelector("a")?.getAttribute("href")).toContain("trades");
  });

  it("says so when there is none to offer", async () => {
    const container = await shown({ ideas: [], ranked_by: "playoffs_change", measure: "points", deadline: null, pickup: "" });

    expect(container.textContent).toContain("No trades");
  });

  it("gains on the figure the Trades page orders by", () => {
    expect(gain(idea, "playoffs_change")).toContain("+2.0");
    expect(gain(idea, "total")).toContain("+12.4");
  });

  it("counts a category league's gain in categories", () => {
    expect(gain(idea, "total", "categories")).toBe("+12.40 cats rest of season");
  });
});
