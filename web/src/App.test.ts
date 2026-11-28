import { Router } from "@effect/ui";
import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect } from "effect";
import { http, HttpResponse } from "msw";
import { App } from "@/App";
import { AppRoute } from "@/lib/route";
import { competitionOf, leagueOf } from "@/test/leagues";
import { page } from "@/test/play";
import { server } from "@/test/server";

const theme = { mode: "light", followsSystem: false } as const;

const menu = HtmlLocator.role("button", { name: /^(Menu|Close menu)$/ });

/** The shell with nothing connected: the rail is all there is to look at. */
function nothingConnected() {
  server.use(
    http.get("/api/competitions", () => HttpResponse.json([])),
    http.get("/api/capabilities", () => HttpResponse.json({ ai: false, limits: { judged: 10 } })),
    // Settings, once the menu's link is followed, which these tests do not read.
    http.get("*", () => new HttpResponse(null, { status: 404 })),
  );
}

describe("App", () => {
  it.layer(page("/"), { buildPerTest: true })("the phone menu", (it) => {
    it.effect("opens, and closes once a link in it is followed", () =>
      Effect.gen(function* () {
        nothingConnected();

        const play = yield* HtmlPlay.make(App, Router.props(AppRoute).pipe(Effect.map(({ route }) => ({ route, ...theme }))));

        yield* play.expect(menu).toHaveAttribute("aria-expanded", "false");

        yield* play.click(menu);

        yield* play.expect(menu).toHaveAttributes({ "aria-expanded": "true", "aria-label": "Close menu" });

        const settings = Locator.inside(Locator.attr("id", "rail"), HtmlLocator.role("link", { name: "Settings" }));

        yield* play.expect(settings).toHaveAttribute("href", "/settings");

        // Following it, as the browser Router does on a click of a link it parses.
        yield* Effect.flatMap(Router.Router, (router) => router.navigate("/settings"));

        yield* play.expect(menu).toHaveAttribute("aria-expanded", "false");
      }),
    );

    it.effect("closes from its own button", () =>
      Effect.gen(function* () {
        nothingConnected();

        const play = yield* HtmlPlay.make(App, Router.props(AppRoute).pipe(Effect.map(({ route }) => ({ route, ...theme }))));

        yield* play.click(menu);

        yield* play.click(menu);

        yield* play.expect(menu).toHaveAttribute("aria-expanded", "false");
      }),
    );
  });
});

describe("the address", () => {
  for (const [from, settled] of [
    ["/nba-yahoo/478.l.1/matchup?week=5&day=2026-11-16", "/nba-yahoo/478.l.1?week=5&day=2026-11-16"],
    ["/nba-yahoo/478.l.1/?week=5", "/nba-yahoo/478.l.1?week=5"],
  ] as const) {
    it.layer(page(from), { buildPerTest: true })(from, (it) => {
      it.effect(`keeps its query when ${from} is settled to the page's own address`, () =>
        Effect.gen(function* () {
          server.use(
            http.get("/api/competitions", () =>
              HttpResponse.json([competitionOf({ key: "nba-yahoo", sport: "basketball" })]),
            ),
            http.get("/api/competitions/nba-yahoo/leagues", () => HttpResponse.json([leagueOf("478.l.1")])),
            http.get("/api/capabilities", () => HttpResponse.json({ ai: false, limits: { judged: 10 } })),
            // The page itself, which this test does not read.
            http.get("*", () => new HttpResponse(null, { status: 404 })),
          );

          yield* HtmlPlay.make(App, Router.props(AppRoute).pipe(Effect.map(({ route }) => ({ route, ...theme }))));

          const route = yield* Router.currentRoute(AppRoute);

          assert.strictEqual(AppRoute.print(route), settled);
        }),
      );
    });
  }
});
