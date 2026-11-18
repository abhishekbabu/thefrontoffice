import { act } from "react";
import { describe, expect, it } from "vitest";
import type { Competition, League, PlayerCard, TeamRef } from "@/lib/api";
import { keys } from "@/lib/queries";
import { RostersPanel } from "@/panels/Rosters";
import { offlineClient, render, settle } from "@/test/render";

const competition = { key: "nfl-sleeper", plans_weeks: false } as Competition;
const league = { league_id: "R1", name: "Sunday Money", detail: "", url: "" } as League;

const teams: TeamRef[] = [
  { team_id: "1", name: "Me", detail: "6-4", url: "", is_mine: true },
  { team_id: "2", name: "Rival", detail: "3-7", url: "", is_mine: false },
];
const card = (id: string, name: string): PlayerCard => ({
  player_id: id,
  columns: { Player: name, Pos: "WR" },
  values: {},
  ruled_out: false,
  roles: { Player: "player" },
});

describe("Rosters", () => {
  it("opens on yours and shows anybody else's from the chips", async () => {
    const client = offlineClient();
    client.setQueryData(keys.teams(competition.key, league.league_id), teams);
    client.setQueryData([...keys.roster(competition.key, league.league_id), null], [card("a", "Lamb")]);
    client.setQueryData([...keys.teamRoster(competition.key, league.league_id, "2"), null], [card("b", "Nacua")]);
    const { container } = await render(<RostersPanel competition={competition} league={league} />, client);

    expect(container.textContent).toContain("Lamb");
    // The record is the league table's; the card names the team and counts its players.
    expect(container.textContent).toContain("1 players");
    expect(container.textContent).not.toContain("6-4");
    const rival = [...container.querySelectorAll<HTMLButtonElement>("button[aria-pressed]")].find((b) =>
      b.textContent?.includes("Rival"),
    )!;
    await act(async () => rival.click());
    await settle();

    expect(container.textContent).toContain("Nacua");
    expect(container.textContent).not.toContain("Lamb");
  });
});
