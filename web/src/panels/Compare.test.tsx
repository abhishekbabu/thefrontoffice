import { act } from "react";
import { describe, expect, it } from "vitest";
import type { Competition, League, PlayerComparison, PlayerDetail } from "@/lib/api";
import { keys } from "@/lib/queries";
import { ComparePanel } from "@/panels/Compare";
import { offlineClient, render, settle } from "@/test/render";
import { playerDetail } from "@/test/players";

const competition = { key: "nfl-sleeper", searches_players: false } as Competition;
const league = { league_id: "C1", name: "Sunday Money", detail: "", url: "" } as League;

const header = (id: string, name: string, owner = ""): PlayerDetail =>
  playerDetail({ player_id: id, name, owner, headline: "18.2" });

describe("Compare", () => {
  it("lays the compared players side by side, a row per measure, and drops one on request", async () => {
    window.localStorage.setItem(`compare:${competition.key}:${league.league_id}`, JSON.stringify(["1", "2"]));
    const comparison: PlayerComparison = {
      players: [header("1", "Lamb", "Rival"), header("2", "Nacua")],
      table: {
        title: "Compared",
        tab: "",
        columns: ["Lamb", "Nacua"],
        rows: [{ label: "Week 11 · Projected", values: ["18.2", "17.9"], tone: "neutral" }],
        absent: "—",
      },
    };
    const client = offlineClient();
    client.setQueryData(keys.compare(competition.key, league.league_id, ["1", "2"]), comparison);
    client.setQueryData(keys.compare(competition.key, league.league_id, ["1"]), {
      players: [comparison.players[0]],
      table: { ...comparison.table, columns: ["Lamb"], rows: [] },
    });
    const { container } = await render(<ComparePanel competition={competition} league={league} />, client);

    const text = container.textContent ?? "";
    expect(text).toContain("Lamb");
    expect(text).toContain("Rival");
    expect(text).toMatch(/Week 11 · Projected18\.217\.9/);

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
});
