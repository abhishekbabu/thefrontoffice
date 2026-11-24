import { act } from "react";
import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import type { Side, Summary } from "@/lib/types";
import { keys } from "@/lib/queries";
import { drawerClient, render, settle } from "@/test/render";
import { server } from "@/test/server";
import { competitionOf, leagueOf } from "@/test/leagues";
import { JudgedAt, MatchupPanel, undated, useJudgeWhenDue } from "@/panels/Matchup";

function Judging({ due, scope, judge }: { due: boolean; scope: string; judge: { mutate: () => void; isPending: boolean } }) {
  useJudgeWhenDue(due, scope, judge);

  return null;
}

function counting() {
  const judge = { calls: 0, isPending: false, mutate: () => void judge.calls++ };

  return judge;
}

describe("judging again on arrival", () => {
  it("asks once for a league whose judgment is due, however often the page renders", async () => {
    const judge = counting();

    const page = await render(<Judging due scope="nfl:L1" judge={judge} />);

    await page.rerender(<Judging due scope="nfl:L1" judge={judge} />);

    expect(judge.calls).toBe(1);
  });

  it("asks again for another league", async () => {
    const judge = counting();

    const page = await render(<Judging due scope="nfl:L1" judge={judge} />);

    await page.rerender(<Judging due scope="nfl:L2" judge={judge} />);

    expect(judge.calls).toBe(2);
  });

  it("never asks where the judgment is not due, or one is already running", async () => {
    const judge = counting();

    await render(<Judging due={false} scope="nfl:L1" judge={judge} />);

    await render(<Judging due scope="nfl:L2" judge={{ ...judge, isPending: true }} />);

    expect(judge.calls).toBe(0);
  });
});

describe("undated", () => {
  it("drops the week the stepper already shows, however the competition words it", () => {
    expect(undated("Week 11 · 19-23 Nov")).toBe("19-23 Nov");
    expect(undated("Gameweek 10 · in progress")).toBe("in progress");
    expect(undated("GW 2 · deadline Sat")).toBe("deadline Sat");
  });
});

describe("JudgedAt", () => {
  it("says stale once, beside when the list was judged, only while something on it has changed", async () => {
    const at = new Date().toISOString();

    const stale = await render(<JudgedAt at={at} stale />);

    const fresh = await render(<JudgedAt at={at} stale={false} />);

    expect(stale.container.textContent).toMatch(/^judged .+ · stale$/);
    expect(fresh.container.textContent).not.toContain("stale");
  });
});

describe("a week a day at a time", () => {
  const competition = competitionOf({ key: "nba-yahoo", browses_weeks: true, browses_days: true });
  const league = leagueOf("478.l.1");

  const side = (name: string, player: string): Side => ({
    name,
    record: "",
    detail: "",
    points: "",
    lineup: [
      {
        player_id: player,
        slot: "PG",
        player,
        mark: "",
        detail: "PG · LAL",
        value: "",
        tone: "neutral",
        today: "vs BOS",
        idle: false,
        kickoff: null,
        scoring: null,
        scored: "",
        projection: "",
        line: [],
      },
    ],
    bench: [],
    reserve: [],
    open_spots: 0,
  });

  const summary = (extra: Partial<Summary>): Summary => ({
    headline: [],
    mine: null,
    opponent: null,
    actions: null,
    fixtures: [],
    boosts: null,
    window: "Week 6 · 23-29 Nov",
    categories: [],
    weeks: { week: 6, current: 6, first: 1, last: 21 },
    days: null,
    ...extra,
  });

  it("shows the day's lineups, and asks for the day stepped to", async () => {
    const asked: string[] = [];

    server.use(
      http.get("*/weeks/6/day", ({ request }) => {
        const on = new URL(request.url).searchParams.get("day") ?? "2026-11-24";

        asked.push(on);

        return HttpResponse.json(
          summary({
            mine: side("Mine", `Mine on ${on}`),
            opponent: side("Theirs", `Theirs on ${on}`),
            headline: [{ label: "Starts", value: "2 – 4", tone: "neutral", url: "", better: null, hint: "" }],
            days: { day: on, first: "2026-11-23", last: "2026-11-29", today: "2026-11-24" },
          }),
        );
      }),
    );

    const client = drawerClient(competition.key, league.league_id);

    client.setQueryData(keys.week(competition.key, league.league_id), summary({ mine: side("Mine", "Week Row"), opponent: side("Theirs", "Their Week Row") }));

    client.setQueryData(keys.untouchables(competition.key, league.league_id), { player_ids: [] });

    const { container } = await render(<MatchupPanel competition={competition} league={league} />, client);

    await settle();

    expect(container.textContent).toContain("Mine on 2026-11-24");
    expect(container.textContent).not.toContain("Week Row");
    expect(container.textContent).toContain("Starts");

    await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="Wed 25 Nov"]')!.click());

    await settle();

    expect(asked).toEqual(["2026-11-24", "2026-11-25"]);
    expect(container.textContent).toContain("Theirs on 2026-11-25");
  });
});
