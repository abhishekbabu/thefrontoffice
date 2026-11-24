import { act } from "react";
import { describe, expect, it } from "vitest";
import type { League, LeagueSchedule, PlayerDetail } from "@/lib/types";
import { keys } from "@/lib/queries";
import { ActivityPanel } from "@/panels/Activity";
import { drawerClient, render, settle } from "@/test/render";
import { playerDetail } from "@/test/players";
import { competitionOf } from "@/test/leagues";

const competition = competitionOf({ key: "nfl-sleeper", finds_trades: true });
const league: League = { league_id: "L1", name: "Sunday Money", detail: "", url: "" };

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
    const client = drawerClient(competition.key, league.league_id);

    client.setQueryData(keys.season(competition.key, league.league_id), schedule);

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
