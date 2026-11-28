import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { assert, describe, it } from "@effect/vitest";
import { Html } from "@effect/ui/html";
import { Effect, Schema } from "effect";
import { http, HttpResponse } from "msw";
import { LeagueHeader } from "@/components/league/page-header";
import { GetWeek } from "@/lib/queries/week";
import type { League } from "@/lib/types";
import { competitionOf } from "@/test/leagues";
import { page, showing } from "@/test/play";
import { server } from "@/test/server";

const competition = competitionOf({ key: "nba-yahoo", refreshes: true });
const league: League = { league_id: "478.l.1", name: "GM 3", detail: "", url: "" };

const refresh = HtmlLocator.role("button", { name: /^Refresh/ });

/** Something on the page reading the league's week, as the matchup does. */
const ReadingWeek = Html.component({
  name: "ReadingWeek",
  model: Schema.Null,
  message: Schema.Never,
  queries: { week: { query: GetWeek, args: () => ({ competition: competition.key, league: league.league_id }) } },
}).make({ init: () => null, update: ($) => $.model, view: (h) => h.div() });

describe("LeagueHeader", () => {
  it.layer(page(), { buildPerTest: true })("refreshing", (it) => {
    it.effect("asks the server to read the league again", () =>
      Effect.gen(function* () {
        const asked: string[] = [];

        server.use(
          http.post("*/refresh", ({ request }) => {
            asked.push(new URL(request.url).pathname);

            return HttpResponse.json({ dropped: 4 });
          }),
        );

        const play = yield* HtmlPlay.make(showing((h) => LeagueHeader(h, { competition, league })), {});

        yield* play.click(refresh);

        assert.deepStrictEqual(asked, ["/api/competitions/nba-yahoo/leagues/478.l.1/refresh"]);
      }),
    );

    it.effect("asks again for every answer about the league on the page", () =>
      Effect.gen(function* () {
        let weeks = 0;

        server.use(
          http.post("*/refresh", () => HttpResponse.json({ dropped: 4 })),
          http.get("*/week", () => {
            weeks++;

            return HttpResponse.json({});
          }),
        );

        const play = yield* HtmlPlay.make(
          showing((h) => h.div(LeagueHeader(h, { competition, league }), ReadingWeek(h, { key: "week" }))),
          {},
        );

        yield* play.click(refresh);

        assert.strictEqual(weeks, 2);
      }),
    );

    it.effect("says why a refresh failed in its own name", () =>
      Effect.gen(function* () {
        server.use(
          http.post("*/refresh", () =>
            HttpResponse.json({ detail: "Could not drop cached reads.", code: "error", remedy: null }, { status: 500 }),
          ),
        );

        const play = yield* HtmlPlay.make(showing((h) => LeagueHeader(h, { competition, league })), {});

        yield* play.click(refresh);

        yield* play.expect(refresh).toHaveAccessibleName(/Could not drop cached reads\./);
      }),
    );

    it.effect("offers no refresh where the competition cannot", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(
          showing((h) => LeagueHeader(h, { competition: { ...competition, refreshes: false }, league })),
          {},
        );

        yield* play.expect(refresh).toBeAbsent();
      }),
    );
  });
});
