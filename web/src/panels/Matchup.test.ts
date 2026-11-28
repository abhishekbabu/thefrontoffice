import { Router } from "@effect/ui";
import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { TestHost } from "@effect/ui/testing";
import { assert, describe, expect, it } from "@effect/vitest";
import { Effect } from "effect";
import { http, HttpResponse } from "msw";
import { AppRoute } from "@/lib/route";
import type { Side, Summary } from "@/lib/types";
import { JudgedAt, MatchupPanel, undated } from "@/panels/Matchup";
import { competitionOf, leagueOf } from "@/test/leagues";
import { page, showing } from "@/test/play";
import { server } from "@/test/server";

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

describe("judging again on arrival", () => {
  const competition = competitionOf({ key: "nfl" });

  /** A model configured, a week with a to-do list, and a kept judgment the server says is due; counts the judgments asked for. */
  function answering({ due, judged = "answers" }: { due: boolean; judged?: "answers" | "hangs" }) {
    const judgments: string[] = [];

    server.use(
      http.get("*/api/capabilities", () => HttpResponse.json({ ai: true })),
      http.get("*/week", () => HttpResponse.json(summary({ actions: [] }))),
      http.get("*/untouchables", () => HttpResponse.json({ player_ids: [] })),
      // Still due after a judgment too: the page must not ask again in a loop.
      http.get("*/judgment", () =>
        HttpResponse.json({ due, answered_at: new Date().toISOString(), answer: { moves: [] } }),
      ),
      http.post("*/judgment", ({ request }) => {
        judgments.push(new URL(request.url).pathname);

        return judged === "hangs" ? new Promise<never>(() => {}) : HttpResponse.json({});
      }),
    );

    return judgments;
  }

  const props = (league: string) =>
    Effect.map(Router.props(AppRoute), ({ route }) => ({ competition, league: leagueOf(league), route }));

  it.layer(page("/nfl/L1"), { buildPerTest: true })("a league whose week has moved on", (it) => {
    it.effect("asks once for a league whose judgment is due, however often the page renders", () =>
      Effect.gen(function* () {
        const judgments = answering({ due: true });
        const play = yield* HtmlPlay.make(MatchupPanel, props("L1"));

        play.root.setProps(yield* props("L1"));

        yield* TestHost.settle;

        assert.deepStrictEqual(judgments, ["/api/competitions/nfl/leagues/L1/judgment"]);

        yield* play.expect(HtmlLocator.role("button", { name: "Judge again" })).toExist();
      }),
    );

    it.effect("asks again for another league", () =>
      Effect.gen(function* () {
        const judgments = answering({ due: true });
        const play = yield* HtmlPlay.make(MatchupPanel, props("L1"));

        play.root.setProps(yield* props("L2"));

        yield* TestHost.settle;

        assert.deepStrictEqual(judgments, [
          "/api/competitions/nfl/leagues/L1/judgment",
          "/api/competitions/nfl/leagues/L2/judgment",
        ]);
      }),
    );

    it.effect("never asks where the judgment is not due", () =>
      Effect.gen(function* () {
        const judgments = answering({ due: false });

        yield* HtmlPlay.make(MatchupPanel, props("L1"));

        assert.deepStrictEqual(judgments, []);
      }),
    );

    it.effect("never asks while one is already running", () =>
      Effect.gen(function* () {
        const judgments = answering({ due: true, judged: "hangs" });
        const play = yield* HtmlPlay.make(MatchupPanel, props("L1"));

        play.root.setProps(yield* props("L2"));

        yield* TestHost.settle;

        assert.deepStrictEqual(judgments, ["/api/competitions/nfl/leagues/L1/judgment"]);
      }),
    );
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
  it.layer(page(), { buildPerTest: true })("the list's judgment", (it) => {
    it.effect("says stale once, beside when the list was judged, only while something on it has changed", () =>
      Effect.gen(function* () {
        const at = new Date().toISOString();

        const stale = yield* HtmlPlay.make(showing((h) => JudgedAt(h, { at, stale: true })), {});

        assert.match(stale.root.text(), /^judged .+ · stale$/);

        const fresh = yield* HtmlPlay.make(showing((h) => JudgedAt(h, { at, stale: false })), {});

        assert.notInclude(fresh.root.text(), "stale");
      }),
    );
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

  it.layer(page("/nba-yahoo/478.l.1"), { buildPerTest: true })("the lineups", (it) => {
    it.effect("shows the day's lineups, and asks for the day stepped to", () =>
      Effect.gen(function* () {
        const asked: string[] = [];

        server.use(
          http.get("*/api/capabilities", () => HttpResponse.json({ ai: false })),
          http.get("*/untouchables", () => HttpResponse.json({ player_ids: [] })),
          http.get("*/week", () =>
            HttpResponse.json(summary({ mine: side("Mine", "Week Row"), opponent: side("Theirs", "Their Week Row") })),
          ),
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

        const props = Effect.map(Router.props(AppRoute), ({ route }) => ({ competition, league, route }));
        const play = yield* HtmlPlay.make(MatchupPanel, props);

        const before = play.root.text();

        assert.include(before, "Mine on 2026-11-24");

        assert.notInclude(before, "Week Row");

        assert.include(before, "Starts");

        yield* play.click(HtmlLocator.role("button", { name: "Wed 25 Nov" }));

        // The address now names the day; the shell hands the page its new route.
        play.root.setProps(yield* props);

        yield* TestHost.settle;

        assert.deepStrictEqual(asked, ["2026-11-24", "2026-11-25"]);

        assert.include(play.root.text(), "Theirs on 2026-11-25");
      }),
    );
  });
});
