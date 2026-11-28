import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, expect, it } from "@effect/vitest";
import { Effect, Option } from "effect";
import { http, HttpResponse } from "msw";
import { AppRoute } from "@/lib/route";
import type { League, TradeIdea, Trades } from "@/lib/types";
import { priced, theirCase, TradesPanel } from "@/panels/Trades";
import { competitionOf } from "@/test/leagues";
import { page } from "@/test/play";
import { server } from "@/test/server";

const idea = (their_playoffs: number, their_points: number, over: Partial<TradeIdea> = {}): TradeIdea => ({
  team_id: "2",
  team: "rival",
  giving: ["A"],
  receiving: ["B"],
  giving_ids: ["a"],
  receiving_ids: ["b"],
  playoffs: 0.9,
  playoffs_change: 0.01,
  their_playoffs_change: 0,
  points: 1,
  their_points,
  playoff_points: 3,
  total: 11,
  their_playoffs,
  pickup: "",
  form: [],
  ...over,
});

describe("why the other manager might take a trade", () => {
  it("is what it is worth, once he is out of the race", () => {
    const said = theirCase(idea(0.01, -2.6));

    expect(said).toContain("1%");

    expect(said).not.toContain("2.6");
  });

  it("is his starters, while he is still chasing a place", () => {
    expect(theirCase(idea(0.4, 1.4))).toContain("+1.4");
  });

  it("is the categories he expects to take, in a category league", () => {
    expect(theirCase(idea(0.01, 0.12), "categories")).toContain("+0.12");
  });
});

describe("a player's pricing", () => {
  it("is found on every trade he is in, under the name the trade lists him by", () => {
    const form = [{ label: "Matthew Golden", value: "priced 18.5", tone: "neutral" as const, url: "", better: null, hint: "" }];

    const ideas = [
      idea(0.4, 1.4, { giving: ["Matthew Golden (WR)"], form }),
      idea(0.4, 1.4, { giving: ["Matthew Golden (WR)", "C (RB)"] }),
    ];

    const pricing = priced(ideas);

    expect(pricing.get("Matthew Golden (WR)")).toBe("priced 18.5");

    expect(pricing.has("C (RB)")).toBe(false);
  });
});

const competition = competitionOf({ key: "nfl-sleeper" });
const league: League = { league_id: "T1", name: "Sunday Money", detail: "", url: "" };
const AT = "/nfl-sleeper/T1/trades";

function shown(trades: Trades) {
  server.use(http.get("*/trades", () => HttpResponse.json(trades)));

  return Effect.gen(function* () {
    const play = yield* HtmlPlay.make(TradesPanel, {
      competition,
      league,
      route: Option.getOrThrow(AppRoute.parse(AT)),
    });

    yield* play.expect(Locator.text("Trades worth offering")).toExist();

    yield* play.expect(HtmlLocator.role("status")).toBeAbsent();

    return play;
  });
}

/** The text of each cell of the table's first row, and of each column head. */
const cells = (play: { root: { all: (l: Locator.Locator) => ReadonlyArray<Locator.Node> } }) => {
  const [first] = play.root.all(Locator.inside(Locator.tag("tbody"), Locator.tag("tr")));

  return first === undefined ? [] : Locator.tag("td").all(first).map(Locator.textOf);
};

const headers = (play: { root: { all: (l: Locator.Locator) => ReadonlyArray<Locator.Node> } }) =>
  play.root.all(HtmlLocator.role("columnheader")).map(Locator.textOf);

describe("Trades", () => {
  it.layer(page(AT), { buildPerTest: true })("the table", (it) => {
    it.effect("names a pickup the trades share once, under the list", () =>
      Effect.gen(function* () {
        const play = yield* shown({
          ideas: [idea(0.4, 1.4), idea(0.4, 1.4, { team_id: "3", receiving: ["C"] })],
          ranked_by: "playoffs_change",
          measure: "points",
          deadline: null,
          pickup: "Chig Okonkwo (TE)",
        });

        assert.lengthOf(play.root.text().split("Chig Okonkwo"), 2);

        assert.notInclude(play.root.text(), "deadline");
      }),
    );

    it.effect("puts each trade on a row, with the regular season's cost beside the playoff gain it buys", () =>
      Effect.gen(function* () {
        const play = yield* shown({
          ideas: [idea(1, 1.7, { points: -3.0, playoff_points: 2.5, total: -1.5, playoffs_change: -0.003 })],
          ranked_by: "total",
          measure: "points",
          deadline: null,
          pickup: "",
        });

        const row = cells(play);

        assert.deepStrictEqual(row.slice(0, 2), ["A", "B"]);

        assert.include(row, "−3.0");

        assert.include(row, "+2.5");

        assert.include(row, "−1.5");

        // The column the list is ordered by is marked as such.
        yield* play
          .expect(Locator.inside(HtmlLocator.role("columnheader", { name: /Total/ }), HtmlLocator.role("img", { name: "ordered by" })))
          .toExist();

        assert.lengthOf(play.root.all(HtmlLocator.role("img", { name: "ordered by" })), 1);
      }),
    );

    it.effect("counts a category league's figures in categories, and says when trading closes", () =>
      Effect.gen(function* () {
        const play = yield* shown({
          ideas: [idea(0.4, 0.12, { points: 0.07, playoff_points: -0.04, total: 0.92 })],
          ranked_by: "playoffs_change",
          measure: "categories",
          deadline: "2027-02-25",
          pickup: "",
        });

        assert.isTrue(headers(play).some((head) => head.includes("cats")));

        assert.include(cells(play), "+0.07");

        assert.include(play.root.text(), "deadline");
      }),
    );

    it.effect("has no playoff column before the playoff weeks are projected", () =>
      Effect.gen(function* () {
        const play = yield* shown({
          ideas: [idea(0.4, 1.4, { playoff_points: null })],
          ranked_by: "playoffs_change",
          measure: "points",
          deadline: null,
          pickup: "",
        });

        assert.isFalse(headers(play).some((head) => head.includes("Playoffs")));
      }),
    );
  });
});
