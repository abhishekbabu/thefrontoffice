import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect } from "effect";
import { http, HttpResponse } from "msw";
import { ComparisonDrawer } from "@/components/league/compare";
import { CompareProvider } from "@/components/league/compare-provider";
import { page, showing } from "@/test/play";
import { REED_WHITE } from "@/test/players";
import { server } from "@/test/server";

const COMPETITION = "nba-yahoo";
const LEAGUE = "L1";

const props = {
  competition: COMPETITION,
  league: LEAGUE,
  comparing: { ids: ["p.1", "p.2"], title: "Pick up Paul Reed, drop Coby White", tags: { "p.1": "In", "p.2": "Out" } },
  open: true,
  back: null,
  swap: null,
};

const drawer = HtmlLocator.role("dialog", { name: "Compare Paul Reed vs Coby White" });

describe("a comparison drawer", () => {
  it.layer(page(), { buildPerTest: true })("a decision's players", (it) => {
    it.effect("heads the grid with the decision, and says which way each player goes", () =>
      Effect.gen(function* () {
        server.use(http.get("*/compare", () => HttpResponse.json(REED_WHITE)));

        const play = yield* HtmlPlay.make(ComparisonDrawer, props);

        const text = Locator.textOf(play.root.get(drawer));

        assert.include(text, "Pick up Paul Reed, drop Coby White");

        assert.match(text, /InPaul Reed/);

        assert.match(text, /OutCoby White/);

        // A decision's players are not a list to edit.
        yield* play.expect(Locator.inside(drawer, HtmlLocator.role("button", { name: /^Remove/ }))).toBeAbsent();
      }),
    );

    it.effect("carries its players over to the Compare page", () =>
      Effect.gen(function* () {
        window.localStorage.removeItem(`compare:${COMPETITION}:${LEAGUE}`);

        server.use(http.get("*/compare", () => HttpResponse.json(REED_WHITE)));

        const play = yield* HtmlPlay.make(
          showing((h) => CompareProvider(h, { props: {}, view: () => ComparisonDrawer(h, { props }) })),
          {},
        );

        yield* play.click(HtmlLocator.role("button", { name: "Open on the Compare page" }));

        assert.deepStrictEqual(JSON.parse(window.localStorage.getItem(`compare:${COMPETITION}:${LEAGUE}`) ?? "null"), [
          "p.1",
          "p.2",
        ]);
      }),
    );
  });
});
