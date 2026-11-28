import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, expect, it } from "@effect/vitest";
import { Effect } from "effect";
import { http, HttpResponse } from "msw";
import { BestTrade, BestTradeEvents, gain } from "@/components/league/best-trade";
import type { TradeIdea, Trades } from "@/lib/types";
import { page } from "@/test/play";
import { server } from "@/test/server";

const idea: TradeIdea = {
  team_id: "2",
  team: "Rival",
  giving: ["Puka Nacua"],
  receiving: ["Bijan Robinson"],
  giving_ids: ["4983"],
  receiving_ids: ["9509"],
  playoffs: 0.9,
  playoffs_change: 0.02,
  their_playoffs_change: 0,
  points: 1,
  their_points: 1,
  playoff_points: 3.2,
  total: 12.4,
  their_playoffs: 0.4,
  pickup: "",
  form: [],
};

/** The best trade as the deadline item shows it, with the Trades page's answer on the server. */
function shown(trades: Trades) {
  server.use(http.get("*/trades", () => HttpResponse.json(trades)));

  return HtmlPlay.make(BestTrade, { competition: "nfl-sleeper", league: "T1" });
}

it.layer(page(), { buildPerTest: true })("the best trade under the deadline item", (it) => {
  it.effect("names the Trades page's first offer, who to make it to and what it gains, with a way there", () =>
    Effect.gen(function* () {
      const play = yield* shown({
        ideas: [idea, { ...idea, team: "Other" }],
        ranked_by: "total",
        measure: "points",
        deadline: null,
        pickup: "",
      });

      const text = play.root.text();

      assert.include(text, "Puka Nacua");

      assert.include(text, "Bijan Robinson");

      assert.include(text, "Rival");

      assert.notInclude(text, "Other");

      assert.include(text, "+12.4");

      const links = play.root.all(Locator.tag("a")).map((link) => link.attrs?.href ?? "");

      assert.lengthOf(links, 1);

      assert.include(links[0] ?? "", "trades");
    }),
  );

  it.effect("opens the trade's two sides side by side", () =>
    Effect.gen(function* () {
      const play = yield* shown({ ideas: [idea], ranked_by: "total", measure: "points", deadline: null, pickup: "" });

      yield* play.click(HtmlLocator.role("button", { name: /Best: give Puka Nacua/ }));

      assert.deepStrictEqual(play.root.emitted, [
        BestTradeEvents.RequestedCompare({
          comparing: { ids: ["4983", "9509"], title: "Trade with Rival", tags: { "4983": "Give", "9509": "Get" } },
        }),
      ]);
    }),
  );

  it.effect("says so when there is none to offer", () =>
    Effect.gen(function* () {
      const play = yield* shown({ ideas: [], ranked_by: "playoffs_change", measure: "points", deadline: null, pickup: "" });

      assert.include(play.root.text(), "No trades");
    }),
  );
});

describe("gain", () => {
  it("gains on the figure the Trades page orders by", () => {
    expect(gain(idea, "playoffs_change")).toContain("+2.0");
    expect(gain(idea, "total")).toContain("+12.4");
  });

  it("counts a category league's gain in categories", () => {
    expect(gain(idea, "total", "categories")).toBe("+12.40 cats rest of season");
  });
});
