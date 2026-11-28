import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect } from "effect";
import { http, HttpResponse } from "msw";
import { Drawers, comparisonDrawer, moveDrawer, type DrawerState } from "@/components/league/drawers";
import { page } from "@/test/play";
import { REED_WHITE } from "@/test/players";
import { server } from "@/test/server";

const COMPETITION = "nba-yahoo";
const LEAGUE = "L1";

const comparison = HtmlLocator.role("dialog", { name: "Compare Paul Reed vs Coby White" });
const reed = HtmlLocator.role("dialog", { name: "Paul Reed" });

/** The server, answering for the two players and their comparison; neither is on your roster. */
function answering() {
  server.use(
    http.get("*/compare", () => HttpResponse.json(REED_WHITE)),
    http.get("*/players/:id", ({ params }) =>
      HttpResponse.json(REED_WHITE.players.find((p) => p.player_id === String(params["id"]))),
    ),
    http.get("*/roster", () => HttpResponse.json([])),
  );
}

/** The page's drawers, opened on `open`. */
const opened = (open: DrawerState) => HtmlPlay.make(Drawers, { competition: COMPETITION, league: LEAGUE, open });

/** The drawer the last request asked the page to open, which the page then does. */
type Play = Effect.Success<ReturnType<typeof opened>>;

function follow(play: Play): DrawerState | null {
  const asked = play.root.emitted.at(-1);

  if (asked?._tag !== "RequestedOpen") return null;

  play.root.setProps({ competition: COMPETITION, league: LEAGUE, open: asked.open });

  return asked.open;
}

describe("a page's drawers", () => {
  it.layer(page(), { buildPerTest: true })("moving between them", (it) => {
    it.effect("swaps a comparison for one of its players, and his Back link swaps it back", () =>
      Effect.gen(function* () {
        answering();

        const play = yield* opened(comparisonDrawer(["p.1", "p.2"]));

        yield* play.expect(comparison).toExist();

        yield* play.click(Locator.inside(comparison, HtmlLocator.role("button", { name: /Paul Reed/ })));

        assert.strictEqual(follow(play)?.kind, "player");

        yield* play.expect(reed).toExist();

        yield* play.expect(comparison).toBeAbsent();

        yield* play.click(Locator.inside(reed, HtmlLocator.role("button", { name: "Compare · Paul Reed vs Coby White" })));

        assert.strictEqual(follow(play)?.kind, "compare");

        yield* play.expect(comparison).toExist();

        yield* play.expect(reed).toBeAbsent();
      }),
    );

    it.effect("opens one player alone rather than a comparison of one", () =>
      Effect.gen(function* () {
        answering();

        const play = yield* opened(comparisonDrawer(["p.1"]));

        yield* play.expect(reed).toExist();
      }),
    );

    it.effect("swaps a move for one of its players, and his Back link swaps it back", () =>
      Effect.gen(function* () {
        answering();

        const move = HtmlLocator.role("dialog", { name: "Waiver by Me" });

        const play = yield* opened(
          moveDrawer({
            when: "11 Nov",
            who: "Me",
            what: "Waiver",
            detail: "",
            is_mine: true,
            bid: "",
            moves: [{ player_id: "p.1", player: "Paul Reed", position: "C", team: "DET", change: "added", manager: "Me" }],
          }),
        );

        yield* play.click(Locator.inside(move, HtmlLocator.role("button", { name: /Paul Reed/ })));

        assert.strictEqual(follow(play)?.kind, "player");

        yield* play.expect(reed).toExist();

        yield* play.click(Locator.inside(reed, HtmlLocator.role("button", { name: "Waiver · Me" })));

        assert.strictEqual(follow(play)?.kind, "move");

        yield* play.expect(move).toExist();
      }),
    );
  });
});
