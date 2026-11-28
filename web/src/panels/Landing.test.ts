import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect } from "effect";
import { http, HttpResponse } from "msw";
import type { League } from "@/lib/types";
import { Landing, LandingEvents } from "@/panels/Landing";
import { competitionOf } from "@/test/leagues";
import { page } from "@/test/play";
import { server } from "@/test/server";

// Only what the landing page reads; the rest of a competition is other pages' business.
const NFL = competitionOf({ key: "nfl-sleeper", label: "NFL", configured: true, blocked: null });
const LEAGUE: League = { league_id: "900", name: "Work League", detail: "3 of 12", url: "https://sleeper.example/900" };

const landing = Effect.gen(function* () {
  server.use(http.get("*/api/competitions/nfl-sleeper/leagues", () => HttpResponse.json([LEAGUE])));

  return yield* HtmlPlay.make(Landing, { competitions: [NFL] });
});

describe("the landing page", () => {
  it.layer(page(), { buildPerTest: true })("leagues", (it) => {
    it.effect("never puts the link to the platform inside the button that opens the league", () =>
      Effect.gen(function* () {
        const play = yield* landing;

        yield* play.expect(HtmlLocator.role("link")).toHaveAttribute("href", LEAGUE.url);

        yield* play.expect(Locator.inside(HtmlLocator.role("button"), HtmlLocator.role("link"))).toBeAbsent();

        yield* play.expect(Locator.inside(HtmlLocator.role("link"), HtmlLocator.role("button"))).toBeAbsent();
      }),
    );

    it.effect("opens the league from its row", () =>
      Effect.gen(function* () {
        const play = yield* landing;

        yield* play.click(HtmlLocator.role("button", { name: /Work League/ }));

        assert.deepStrictEqual(play.root.emitted, [LandingEvents.Picked({ competition: NFL, league: LEAGUE })]);
      }),
    );
  });
});
