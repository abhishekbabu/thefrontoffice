import { act } from "react";
import { describe, expect, it } from "vitest";
import type { ActivityRow, Competition, League, LeagueSchedule, PlayerDetail } from "@/lib/api";
import { keys } from "@/lib/queries";
import { ActivityPanel } from "@/panels/Activity";
import { sections } from "@/components/ui/move";
import { offlineClient, render, settle } from "@/test/render";
import { playerDetail } from "@/test/players";

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
      who: "Rival ↔ Me",
      what: "Trade",
      detail: "+Star QB, $5 FAAB · +Bad RB",
      is_mine: false,
      bid: "",
      moves: [
        { player_id: "qb1", player: "Star QB", position: "QB", team: "BUF", change: "added", manager: "Rival" },
        { player_id: "", player: "$5 FAAB", position: "", team: "", change: "added", manager: "Rival" },
        { player_id: "rb2", player: "Bad RB", position: "RB", team: "MIA", change: "added", manager: "Me" },
        { player_id: "rb2", player: "Bad RB", position: "RB", team: "MIA", change: "dropped", manager: "Rival" },
        { player_id: "qb1", player: "Star QB", position: "QB", team: "BUF", change: "dropped", manager: "Me" },
      ],
    },
  ],
};

const STAR_QB: PlayerDetail = playerDetail({ player_id: "qb1", name: "Star QB", position: "QB", team: "BUF" });

describe("League activity", () => {
  it("opens a trade in full, by who got whom", async () => {
    const client = offlineClient();
    client.setQueryData(keys.schedule(competition.key, league.league_id), schedule);
    client.setQueryData(keys.teams(competition.key, league.league_id), []);
    client.setQueryData(keys.player(competition.key, league.league_id, "qb1"), STAR_QB);
    const { container } = await render(<ActivityPanel competition={competition} league={league} />, client);

    const row = [...container.querySelectorAll<HTMLElement>("[role=button]")].find((el) =>
      el.textContent?.includes("Star QB"),
    )!;
    await act(async () => row.click());
    await settle();

    const dialog = document.querySelector("[role=dialog]")!;
    expect(dialog.getAttribute("aria-label")).toBe("Trade by Rival ↔ Me");
    expect(dialog.textContent).toMatch(/To Rival.*Star QB.*\$5 FAAB/);
    expect(dialog.textContent).toContain("To Rival");
    expect(dialog.textContent).toContain("To Me");
    expect(dialog.textContent).toContain("QB · BUF");

    // A player opened from the move takes its place, with the way back to it.
    const player = [...dialog.querySelectorAll<HTMLElement>("[role=button]")].find((el) =>
      el.textContent?.includes("Star QB"),
    )!;
    await act(async () => player.click());
    await settle(400);
    expect(document.querySelector("[aria-label='Trade by Rival ↔ Me']")).toBeNull();
    const back = [...document.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
      b.textContent?.includes("Trade · Rival ↔ Me"),
    )!;
    await act(async () => back.click());
    await settle(400);
    expect(document.querySelector("[aria-label='Trade by Rival ↔ Me']")).not.toBeNull();
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
