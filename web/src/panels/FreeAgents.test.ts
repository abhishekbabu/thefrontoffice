import { Router } from "@effect/ui";
import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect } from "effect";
import { http, HttpResponse } from "msw";
import { AppRoute } from "@/lib/route";
import type { League, PlayerCall, PlayerCard, PlayerPage } from "@/lib/types";
import { FreeAgentsPanel, withCalls } from "@/panels/FreeAgents";
import { competitionOf } from "@/test/leagues";
import { page } from "@/test/play";
import { server } from "@/test/server";

const call = (player_id: string, decision: PlayerCall["decision"], stale = false): PlayerCall => ({
  player_id,
  decision,
  drop: "",
  reason: "",
  judged_at: null,
  stale,
});

describe("the calls a judging makes", () => {
  it("take the place of the kept ones on the same players and leave the rest", () => {
    const kept = [call("a", "PASS", true), call("b", "WATCH")];

    const merged = withCalls(kept, [call("a", "ADD"), call("c", "PASS")]);

    assert.deepStrictEqual(Object.fromEntries(merged.map((c) => [c.player_id, [c.decision, c.stale]])), {
      a: ["ADD", false],
      b: ["WATCH", false],
      c: ["PASS", false],
    });
  });
});

const competition = competitionOf({ key: "nfl-sleeper", judges_wire: true });
const league: League = { league_id: "R1", name: "Sunday Money", detail: "", url: "" };

const card = (id: string): PlayerCard => ({
  player_id: id,
  columns: { Player: id },
  values: {},
  ruled_out: false,
  notes: {},
  tones: {},
  roles: { Player: "player" },
});

/** A page of the wire: `players` of `total`, fifty to a page. */
const wire = (players: PlayerCard[], total = players.length): PlayerPage => ({
  players,
  total,
  offset: 0,
  limit: 50,
  positions: ["WR", "TE"],
  views: [],
  hints: {},
});

/** The wire's pages, asked with these offsets; a model configured that judges two at once. */
function answering(pages: PlayerPage, offsets: string[] = []) {
  server.use(
    http.get("*/capabilities", () => HttpResponse.json({ ai: true, limits: { judged: 2 } })),
    http.get("*/free-agents", ({ request }) => {
      offsets.push(new URL(request.url).searchParams.get("offset") ?? "");

      return HttpResponse.json(pages);
    }),
  );
}

const opened = Effect.gen(function* () {
  const route = yield* Router.currentRoute(AppRoute);

  return yield* HtmlPlay.make(FreeAgentsPanel, { competition, league, route });
});

describe("FreeAgents", () => {
  it.layer(page("/nfl-sleeper/R1/free-agents"), { buildPerTest: true })("the wire", (it) => {
    it.effect("puts a judging's calls under their rows without reading them back", () =>
      Effect.gen(function* () {
        let reads = 0;

        answering(wire([card("a"), card("b"), card("c")]));

        server.use(
          http.get("*/free-agents/calls", () => {
            reads++;

            return HttpResponse.json([]);
          }),
          http.post("*/free-agents/calls", () => HttpResponse.json([{ ...call("a", "ADD"), drop: "z" }])),
        );

        const play = yield* opened;

        yield* play.click(HtmlLocator.role("button", { name: "Judge the first 2 shown" }));

        assert.include(play.root.text(), "Add, drop z");

        assert.strictEqual(reads, 1);
      }),
    );

    it.effect("says why a judging failed", () =>
      Effect.gen(function* () {
        answering(wire([card("a")]));

        server.use(
          http.get("*/free-agents/calls", () => HttpResponse.json([])),
          http.post("*/free-agents/calls", () =>
            HttpResponse.json({ detail: "The model is busy.", code: "error", remedy: null }, { status: 503 }),
          ),
        );

        const play = yield* opened;

        yield* play.click(HtmlLocator.role("button", { name: "Judge the first 1 shown" }));

        yield* play.expect(HtmlLocator.role("alert")).toExist();

        assert.include(play.root.text(), "The model is busy.");
      }),
    );

    it.effect("pages on, and starts again at the first page when the ask changes", () =>
      Effect.gen(function* () {
        const offsets: string[] = [];

        answering(wire([card("a")], 120), offsets);

        server.use(http.get("*/free-agents/calls", () => HttpResponse.json([])));

        const play = yield* opened;

        assert.include(play.root.text(), "Page 1 of 3");

        yield* play.click(HtmlLocator.role("button", { name: "Next page" }));

        assert.include(play.root.text(), "51-51 of 120");

        yield* play.click(HtmlLocator.role("button", { name: "WR" }));

        assert.deepStrictEqual(offsets, ["0", "50", "0"]);

        yield* play.click(HtmlLocator.role("button", { name: "Clear filters" }));

        yield* play.expect(HtmlLocator.role("button", { name: "Clear filters" })).toBeAbsent();
      }),
    );
  });
});
