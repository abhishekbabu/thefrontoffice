import { act } from "react";
import { describe, expect, it } from "vitest";
import type { ActivityRow, Competition, League, LeagueSchedule } from "@/lib/api";
import { keys } from "@/lib/queries";
import { LeaguePanel, sections } from "@/panels/LeaguePanel";
import { offlineClient, render, settle } from "@/test/render";

const competition = { key: "nfl-sleeper", finds_trades: true } as Competition;
const league = { league_id: "L1", name: "Sunday Money", detail: "", url: "" } as League;

const schedule: LeagueSchedule = {
  headline: [],
  season: [],
  standings: [],
  matches: [],
  activity: [
    {
      when: "16 Nov",
      who: "Rival",
      what: "Trade",
      detail: "+Star QB, -Bad RB",
      is_mine: false,
      bid: "",
      moves: [
        { player_id: "qb1", player: "Star QB", position: "QB", team: "BUF", change: "added", manager: "Rival" },
        { player_id: "rb2", player: "Bad RB", position: "RB", team: "MIA", change: "added", manager: "Me" },
        { player_id: "rb2", player: "Bad RB", position: "RB", team: "MIA", change: "dropped", manager: "Rival" },
        { player_id: "qb1", player: "Star QB", position: "QB", team: "BUF", change: "dropped", manager: "Me" },
      ],
    },
  ],
};

describe("League activity", () => {
  it("opens a trade in full, by who got whom", async () => {
    const client = offlineClient();
    client.setQueryData(keys.schedule(competition.key, league.league_id), schedule);
    client.setQueryData(keys.teams(competition.key, league.league_id), []);
    const { container } = await render(<LeaguePanel competition={competition} league={league} />, client);

    const row = [...container.querySelectorAll<HTMLElement>("[role=button]")].find((el) =>
      el.textContent?.includes("Star QB"),
    )!;
    await act(async () => row.click());
    await settle();

    const dialog = document.querySelector("[role=dialog]")!;
    expect(dialog.getAttribute("aria-label")).toBe("Trade by Rival");
    expect(dialog.textContent).toContain("To Rival");
    expect(dialog.textContent).toContain("To Me");
    expect(dialog.textContent).toContain("QB · BUF");
  });
});

describe("sections", () => {
  it("reads one manager's move as what he added and what he let go", () => {
    const claim: ActivityRow = {
      when: "11 Nov",
      who: "Me",
      what: "Waiver",
      detail: "",
      is_mine: true,
      bid: "$14",
      moves: [
        { player_id: "wr9", player: "Waiver WR", position: "WR", team: "NYJ", change: "added", manager: "Me" },
        { player_id: "rb1", player: "Good RB", position: "RB", team: "BUF", change: "dropped", manager: "Me" },
      ],
    };

    expect(sections(claim).map((s) => [s.title, s.moves.map((m) => m.player)])).toEqual([
      ["Added", ["Waiver WR"]],
      ["Dropped", ["Good RB"]],
    ]);
  });
});
