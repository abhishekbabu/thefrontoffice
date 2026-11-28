import { Router } from "@effect/ui";
import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect, Option } from "effect";
import { http, HttpResponse } from "msw";
import { AppRoute } from "@/lib/route";
import type { LeagueSchedule } from "@/lib/types";
import { LeaguePanel } from "@/panels/LeaguePanel";
import { competitionOf, leagueOf } from "@/test/leagues";
import { page } from "@/test/play";
import { server } from "@/test/server";

const NFL = competitionOf({ key: "nfl-sleeper" });
const LEAGUE = leagueOf("L1");
const AT = "/nfl-sleeper/L1/league";

const standing = (rank: number, name: string, team_id: string, extra: Partial<LeagueSchedule["standings"][number]> = {}) => ({
  rank,
  name,
  team_id,
  detail: "",
  record: "",
  points: "100",
  points_against: "",
  playoffs: "",
  waiver_budget: "",
  waiver_order: "",
  is_mine: false,
  ...extra,
});

function answering(standings: LeagueSchedule["standings"]) {
  const schedule: LeagueSchedule = { headline: [], season: [], standings, matches: [], activity: [] };

  server.use(http.get("*/season", () => HttpResponse.json(schedule)));
}

const table = Effect.gen(function* () {
  const route = Option.getOrThrow(AppRoute.parse(AT));

  return yield* HtmlPlay.make(LeaguePanel, { competition: NFL, league: LEAGUE, route });
});

describe("the league table", () => {
  it.layer(page(AT), { buildPerTest: true })("a row", (it) => {
    it.effect("opens that team's roster", () =>
      Effect.gen(function* () {
        answering([standing(1, "Rival", "4", { is_mine: false }), standing(2, "Mine", "5", { is_mine: true })]);

        const play = yield* table;

        yield* play.click(HtmlLocator.role("button", { name: /Rival/ }));

        const router = yield* Router.Router;

        assert.strictEqual(router.location().url, "/nfl-sleeper/L1/rosters?team=4");
      }),
    );

    it.effect("shows only the columns the league fills, and marks your own team in words", () =>
      Effect.gen(function* () {
        answering([standing(1, "Rival", "4"), standing(2, "Mine", "5", { is_mine: true, waiver_budget: "$40" })]);

        const play = yield* table;

        const heads = play.root.all(HtmlLocator.role("columnheader")).map(Locator.textOf);

        assert.deepStrictEqual(heads, ["#", "Team", "Pts", "FAAB"]);

        assert.include(play.root.text(), "Mineyou");
      }),
    );

    it.effect("says there is no table where the league has none", () =>
      Effect.gen(function* () {
        answering([]);

        const play = yield* table;

        assert.include(play.root.text(), "No table");
      }),
    );
  });
});
