import { describe, expect, it } from "vitest";
import type { Competition, League, TradeIdea, Trades } from "@/lib/api";
import { keys } from "@/lib/queries";
import { changes, theirCase, TradesPanel } from "@/panels/Trades";
import { offlineClient, render } from "@/test/render";

const idea = (their_playoffs: number, their_points: number, over: Partial<TradeIdea> = {}): TradeIdea => ({
  team_id: "2",
  team: "rival",
  giving: ["A"],
  receiving: ["B"],
  playoffs: 0.9,
  playoffs_change: 0.01,
  their_playoffs_change: 0,
  points: 1,
  their_points,
  playoff_points: 3,
  their_playoffs,
  pickup: "",
  form: [],
  ...over,
});

describe("why the other manager might take a trade", () => {
  it("is what it is worth, once he is out of the race", () => {
    expect(theirCase(idea(0.01, -2.6))).toContain("out of the race");
  });

  it("is his starters, while he is still chasing a place", () => {
    expect(theirCase(idea(0.4, 1.4))).toContain("+1.4");
  });
});

describe("what a trade does for you", () => {
  it("says the playoff chance and the regular season where each moves noticeably", () => {
    const said = changes(idea(0.4, 1.4, { playoffs_change: 0.012, points: 1.3 }));

    expect(said).toHaveLength(2);
    expect(said[0]).toContain("+1.2");
    expect(said[1]).toContain("+1.3");
  });

  it("leaves out a change under half a point", () => {
    expect(changes(idea(0.4, 1.4, { playoffs_change: 0.0004, points: 0.2 }))).toEqual([]);
  });
});

describe("Trades", () => {
  const competition = { key: "nfl-sleeper" } as Competition;
  const league = { league_id: "T1", name: "Sunday Money", detail: "", url: "" } as League;

  it("names a pickup the trades share once, under the list", async () => {
    const client = offlineClient();
    const trades: Trades = {
      ideas: [idea(0.4, 1.4), idea(0.4, 1.4, { team_id: "3", receiving: ["C"] })],
      pickup: "Chig Okonkwo (TE)",
    };
    client.setQueryData(keys.trades(competition.key, league.league_id), trades);
    const { container } = await render(<TradesPanel competition={competition} league={league} />, client);

    expect(container.textContent?.split("Chig Okonkwo")).toHaveLength(2);
    expect(container.textContent).not.toContain("deadline");
  });
});
