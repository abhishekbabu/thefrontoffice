import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect, Option } from "effect";
import { http, HttpResponse } from "msw";
import { CompareProvider } from "@/components/league/compare-provider";
import { scopeOf } from "@/lib/compare";
import { AppRoute } from "@/lib/route";
import type { CaptureStatus, Competition, League, PlayerComparison, PlayerDetail, PlayerRef } from "@/lib/types";
import { ComparePanel } from "@/panels/Compare";
import { competitionOf } from "@/test/leagues";
import { page, showing } from "@/test/play";
import { playerDetail } from "@/test/players";
import { server } from "@/test/server";

const competition = competitionOf({ key: "nfl-sleeper", searches_players: false });
const league: League = { league_id: "C1", name: "Sunday Money", detail: "", url: "" };
const AT = "/nfl-sleeper/C1/compare";

const header = (id: string, name: string, owner = ""): PlayerDetail =>
  playerDetail({ player_id: id, name, owner, headline: "18.2" });

/** The Compare page under the list every page shares, holding `ids` for its league. */
function comparing(on: Competition, at: League, ids: string[] = []) {
  const route = Option.getOrThrow(AppRoute.parse(AT));

  return HtmlPlay.make(
    showing((h) =>
      CompareProvider(h, {
        props: { initial: { [scopeOf(on.key, at.league_id)]: ids } },
        view: () => ComparePanel(h, { props: { competition: on, league: at, route } }),
      }),
    ),
    {},
  );
}

describe("Compare", () => {
  it.layer(page(AT), { buildPerTest: true })("the page", (it) => {
    it.effect("lays the compared players side by side, a row per measure, and drops one on request", () =>
      Effect.gen(function* () {
        const comparison: PlayerComparison = {
          players: [header("1", "Lamb", "Rival"), header("2", "Nacua")],
          tables: [
            {
              title: "Week 11",
              tab: "",
              columns: ["Lamb", "Nacua"],
              rows: [
                { label: "Targets a game", values: ["8.1", "9.4"], tone: "neutral", better: "higher", best: [1] },
                { label: "Opponent", values: ["vs MIA", "vs NYJ"], tone: "neutral", better: null, best: [] },
              ],
              absent: "—",
            },
          ],
        };

        const asked: string[][] = [];

        server.use(
          http.get("*/compare", ({ request }) => {
            const ids = new URL(request.url).searchParams.getAll("ids");

            asked.push(ids);

            return HttpResponse.json(
              ids.length === 1 ? { players: [comparison.players[0]], tables: [] } : comparison,
            );
          }),
        );

        const play = yield* comparing(competition, league, ["1", "2"]);

        yield* play.expect(HtmlLocator.role("button", { name: "Remove Nacua" })).toExist();

        const text = play.root.text();

        assert.include(text, "Lamb");

        assert.include(text, "Rival");

        // The heading once, over its rows, not as a prefix on each label.
        assert.match(text, /Week 11Targets a game8\.19\.4best/);

        // Only the better figure is marked, and only in a row that compares.
        assert.lengthOf(text.match(/best/g) ?? [], 1);

        yield* play.click(HtmlLocator.role("button", { name: "Remove Nacua" }));

        yield* play.expect(HtmlLocator.role("button", { name: "Remove Nacua" })).toBeAbsent();

        assert.deepStrictEqual(asked.at(-1), ["1"]);

        assert.deepStrictEqual(JSON.parse(window.localStorage.getItem(`compare:${scopeOf(competition.key, league.league_id)}`) ?? "null"), [
          "1",
        ]);
      }),
    );

    it.effect("says what to do when nobody is compared yet", () =>
      Effect.gen(function* () {
        const play = yield* comparing(competition, { ...league, league_id: "C2" });

        assert.include(play.root.text(), "Nobody to compare");
      }),
    );

    it.effect("finds a player by name, and says when a browser sync limits who can be found", () =>
      Effect.gen(function* () {
        const nba = competitionOf({ key: "nba-yahoo", platform: "yahoo", searches_players: true, syncs: true });
        const found: PlayerRef[] = [{ player_id: "466.p.1", name: "Cam Johnson", detail: "SF · DEN" }];
        const status: CaptureStatus = { active: true, synced_at: null, leagues: [], session: null };

        server.use(
          http.get("*/leagues/N1/players", ({ request }) =>
            HttpResponse.json(new URL(request.url).searchParams.get("search") === "cam" ? found : []),
          ),
          http.get("*/platforms/yahoo/capture", () => HttpResponse.json(status)),
        );

        const play = yield* comparing(nba, { ...league, league_id: "N1" });

        yield* play.expect(HtmlLocator.role("textbox", { name: "Find a player to compare" })).toExist();

        assert.notInclude(play.root.text(), "Synced players only");

        yield* play.type(HtmlLocator.role("textbox", { name: "Find a player to compare" }), "cam");

        yield* play.expect(HtmlLocator.role("button", { name: /Cam Johnson/ })).toExist();

        assert.include(play.root.text(), "Synced players only");
      }),
    );
  });
});
