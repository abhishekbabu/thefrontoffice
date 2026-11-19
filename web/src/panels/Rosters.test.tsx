import { act } from "react";
import { describe, expect, it } from "vitest";
import type { Competition, League, Outlook, PlayerCard, TeamRef } from "@/lib/api";
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
  notes: {},
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

  it("lists only the weeks somebody misses, and one line when nobody does", async () => {
    const planning = { ...competition, plans_weeks: true } as Competition;
    const week = (n: number, missing: string[] = []): Outlook["weeks"][number] => ({
      week: n,
      points: 120,
      missing,
      short_by: 0,
      short: false,
      light: [],
      heavy: false,
      provisional: false,
      fix: "",
      gain: 0,
    });
    const show = async (outlook: Outlook) => {
      const client = offlineClient();
      client.setQueryData(keys.teams(competition.key, league.league_id), teams);
      client.setQueryData([...keys.roster(competition.key, league.league_id), null], [card("a", "Lamb")]);
      client.setQueryData(keys.weeksAhead(competition.key, league.league_id, ""), outlook);
      return (await render(<RostersPanel competition={planning} league={league} />, client)).container.textContent;
    };

    const some = await show({
      ...NO_GRID,
      usual: 120,
      measure: "proj",
      weeks: [week(12), week(13, ["Josh Allen (bye)"]), week(14)],
    });
    expect(some).toContain("Week 13");
    expect(some).not.toContain("Week 12");
    expect(some).not.toContain("Week 14");

    const none = await show({ ...NO_GRID, usual: 120, measure: "proj", weeks: [week(12), week(13), week(14)] });
    expect(none).toContain("through week 14");
    expect(none).not.toContain("Week 12");
  });

  it("counts a basketball week in games, and lists a light or heavy one with its stream", async () => {
    const planning = { ...competition, plans_weeks: true } as Competition;
    const week = (n: number, more: Partial<Outlook["weeks"][number]> = {}): Outlook["weeks"][number] => ({
      week: n,
      points: 40,
      missing: [],
      short_by: 0,
      short: false,
      light: [],
      heavy: false,
      provisional: false,
      fix: "",
      gain: 0,
      ...more,
    });
    const client = offlineClient();
    client.setQueryData(keys.teams(competition.key, league.league_id), teams);
    client.setQueryData([...keys.roster(competition.key, league.league_id), null], [card("a", "Brunson")]);
    client.setQueryData(keys.weeksAhead(competition.key, league.league_id, ""), {
      usual: 40.5,
      ...NO_GRID,
      measure: "games",
      weeks: [
        week(6),
        week(7, { points: 34, short: true, short_by: 6.5, light: ["Jalen Brunson (2 games)"] }),
        week(8, { heavy: true, fix: "Pick up Kris Dunn (PG, LAC, 4 games), drop Coby White (2 games)", gain: 2 }),
        week(9, { provisional: true }),
      ],
    } satisfies Outlook);
    const text = (await render(<RostersPanel competition={planning} league={league} />, client)).container
      .textContent;

    expect(text).not.toContain("Week 6");
    expect(text).toContain("34 games");
    expect(text).toContain("Jalen Brunson (2 games)");
    expect(text).toContain("heavy");
    expect(text).toContain("Kris Dunn");
    expect(text).toContain("+2 games");
    expect(text).toContain("Week 9");
    expect(text).toContain("provisional");
  });

  it("shows FPL's weeks ahead as a fixture grid of only the players to watch", async () => {
    const fpl = { key: "premier-league-fpl", plans_weeks: true } as Competition;
    const client = offlineClient();
    client.setQueryData(keys.teams(fpl.key, league.league_id), teams);
    client.setQueryData([...keys.roster(fpl.key, league.league_id), null], [card("a", "Haaland")]);
    client.setQueryData(keys.weeksAhead(fpl.key, league.league_id, ""), {
      usual: null,
      measure: "proj",
      weeks: [],
      run_weeks: [11, 12],
      runs: [
        {
          player_id: "a",
          player: "Haaland",
          detail: "FWD · MCI",
          weeks: [
            { week: 11, games: [{ opponent: "ARS", home: false, difficulty: 5 }] },
            { week: 12, games: [] },
          ],
          flags: ["blank GW12"],
        },
      ],
      clear: 14,
      warnings: [{ label: "GW12", value: "1 blank: Haaland", tone: "warning", url: "", better: null, hint: "" }],
    } satisfies Outlook);
    const text = (await render(<RostersPanel competition={fpl} league={league} />, client)).container.textContent;

    expect(text).toContain("1 to watch");
    expect(text).toContain("ARS A 5");
    expect(text).toContain("blank GW12");
    expect(text).toContain("1 blank: Haaland");
    expect(text).toContain("14 others: no blanks, doubles or hard runs through GW12.");
  });
});

const NO_GRID = { run_weeks: [], runs: [], clear: 0, warnings: [] };
