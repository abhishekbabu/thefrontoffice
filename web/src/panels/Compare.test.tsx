import { act } from "react";
import { describe, expect, it } from "vitest";
import type { CaptureStatus, Competition, League, PlayerComparison, PlayerDetail, PlayerRef } from "@/lib/api";
import { keys } from "@/lib/queries";
import { ComparePanel } from "@/panels/Compare";
import { offlineClient, render, settle, typeInto } from "@/test/render";
import { playerDetail } from "@/test/players";

const competition = { key: "nfl-sleeper", searches_players: false } as Competition;
const league: League = { league_id: "C1", name: "Sunday Money", detail: "", url: "" };

const header = (id: string, name: string, owner = ""): PlayerDetail =>
  playerDetail({ player_id: id, name, owner, headline: "18.2" });

describe("Compare", () => {
  it("lays the compared players side by side, a row per measure, and drops one on request", async () => {
    window.localStorage.setItem(`compare:${competition.key}:${league.league_id}`, JSON.stringify(["1", "2"]));
    const comparison: PlayerComparison = {
      players: [header("1", "Lamb", "Rival"), header("2", "Nacua")],
      tables: [
        {
          title: "Week 11",
          tab: "",
          columns: ["Lamb", "Nacua"],
          rows: [
            { label: "Targets a game", values: ["8.1", "9.4"], tone: "neutral", better: "higher", best: [1] },
            { label: "Opponent", values: ["vs MIA", "vs NYJ"], tone: "neutral", better: null, best: [] },
          ],
          absent: "—",
        },
      ],
    };
    const client = offlineClient();
    client.setQueryData(keys.compare(competition.key, league.league_id, ["1", "2"]), comparison);
    client.setQueryData(keys.compare(competition.key, league.league_id, ["1"]), {
      players: [comparison.players[0]],
      tables: [],
    });
    const { container } = await render(<ComparePanel competition={competition} league={league} />, client);

    const text = container.textContent ?? "";
    expect(text).toContain("Lamb");
    expect(text).toContain("Rival");
    // The heading once, over its rows, not as a prefix on each label.
    expect(text).toMatch(/Week 11Targets a game8\.19\.4best/);
    expect(text).not.toContain("Week 11 ·");
    // Only the better figure is marked, and only in a row that compares.
    expect(text.match(/best/g)).toHaveLength(1);

    await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="Remove Nacua"]')!.click());
    await settle();
    expect(JSON.parse(window.localStorage.getItem(`compare:${competition.key}:${league.league_id}`)!)).toEqual(["1"]);
  });

  it("says what to do when nobody is compared yet", async () => {
    const { container } = await render(
      <ComparePanel competition={competition} league={{ ...league, league_id: "C2" }} />,
    );
    expect(container.textContent).toContain("Nobody to compare");
  });

  it("finds a player by name, and says when a browser sync limits who can be found", async () => {
    const nba = { key: "nba-yahoo", platform: "yahoo", searches_players: true, syncs: true } as Competition;
    const found: PlayerRef[] = [{ player_id: "466.p.1", name: "Cam Johnson", detail: "SF · DEN" }];
    const client = offlineClient();
    client.setQueryData(keys.playerSearch(nba.key, "N1", "cam"), found);
    const status: CaptureStatus = { active: true, synced_at: null, leagues: [], session: null };
    client.setQueryData(keys.capture("yahoo"), status);
    const { container } = await render(<ComparePanel competition={nba} league={{ ...league, league_id: "N1" }} />, client);
    expect(container.textContent).not.toContain("Synced players only");

    await typeInto(container.querySelector("input")!, "cam");
    await settle();

    expect(container.textContent).toContain("Cam Johnson");
    expect(container.textContent).toContain("Synced players only");
  });
});
