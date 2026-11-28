import { Router } from "@effect/ui";
import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect, Option } from "effect";
import { http, HttpResponse } from "msw";
import { AppRoute } from "@/lib/route";
import { kickoff } from "@/lib/times";
import type { LeagueSchedule, Match, Slate } from "@/lib/types";
import { FixturesPanel, Games } from "@/panels/Fixtures";
import { competitionOf, leagueOf } from "@/test/leagues";
import { page, showing } from "@/test/play";
import { playerDetail } from "@/test/players";
import { server } from "@/test/server";

const game = (extra: Partial<Match> = {}): Match => ({
  label: "Sun 15 Nov",
  home: "BUF",
  away: "MIA",
  detail: "",
  tone: "neutral",
  home_score: null,
  away_score: null,
  kickoff: null,
  yours: [],
  theirs: [],
  ...extra,
});

const games = (rows: Match[], extra: { byes?: string[]; note?: string } = {}) =>
  HtmlPlay.make(showing((h) => Games(h, { rows, ...extra })), {});

describe("Games", () => {
  it.layer(page(), { buildPerTest: true })("the list", (it) => {
    it.effect("puts each side's score beside it once the game has kicked off", () =>
      Effect.gen(function* () {
        const play = yield* games([game({ home_score: 27, away_score: 20, detail: "Final" })]);

        assert.include(play.root.text(), "MIA 20 at BUF 27");
      }),
    );

    it.effect("shows no score for a game yet to start", () =>
      Effect.gen(function* () {
        const play = yield* games([game()]);

        assert.include(play.root.text(), "MIA at BUF");

        assert.notMatch(play.root.text(), /\d+ at/);
      }),
    );

    it.effect("shows the start time in the viewer's zone", () =>
      Effect.gen(function* () {
        const iso = "2026-11-22T18:00:00Z";

        const play = yield* games([game({ kickoff: iso })]);

        assert.include(play.root.text(), new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }));
      }),
    );

    it.effect("says each kickoff once, over the games that share it", () =>
      Effect.gen(function* () {
        const early = "2026-11-22T18:00:00Z";
        const late = "2026-11-22T21:25:00Z";

        const play = yield* games([
          game({ kickoff: early }),
          game({ home: "DAL", away: "NYG", kickoff: early }),
          game({ home: "SF", away: "SEA", kickoff: late }),
        ]);

        const text = play.root.text();

        assert.lengthOf(text.split(kickoff(early)), 2);

        assert.lengthOf(text.split(kickoff(late)), 2);

        assert.isAbove(text.indexOf(kickoff(late)), text.indexOf("NYG at DAL"));
      }),
    );

    it.effect("names whose players are in a game, yours apart from your opponent's", () =>
      Effect.gen(function* () {
        const both = game({
          yours: [{ player_id: "1", name: "Josh Allen", detail: "QB · starting" }],
          theirs: [{ player_id: "2", name: "Tua Tagovailoa", detail: "QB · starting" }],
        });

        const play = yield* games([both]);

        assert.include(play.root.text(), "YouJosh Allen");

        assert.include(play.root.text(), "OppTua Tagovailoa");
      }),
    );

    it.effect("lists the week's byes on one line, and none where every club plays", () =>
      Effect.gen(function* () {
        const withByes = yield* games([game()], { byes: ["KC", "LAR"] });

        assert.include(withByes.root.text(), "ByesKC, LAR");

        const without = yield* games([game()]);

        assert.notInclude(without.root.text(), "Byes");
      }),
    );

    it.effect("says when the week's schedule is not final, and nothing for a week that is", () =>
      Effect.gen(function* () {
        const pending = yield* games([game()], { note: "Schedule not final: no games yet 4-11 Dec." });

        assert.include(pending.root.text(), "4-11 Dec");

        const settled = yield* games([game()]);

        assert.notInclude(settled.root.text(), "Schedule");
      }),
    );
  });
});

const NFL = competitionOf({ key: "nfl-sleeper" });
const LEAGUE = leagueOf("L1");
const AT = "/nfl-sleeper/L1/fixtures";

const LAMB = playerDetail({ player_id: "1", name: "Lamb", position: "WR", team: "DAL" });

/** The page on the league's schedule, as a competition that does not page through the season reads it. */
function scheduled(matches: Match[]) {
  const schedule: LeagueSchedule = { headline: [], season: [], standings: [], matches, activity: [] };

  server.use(
    http.get("*/season", () => HttpResponse.json(schedule)),
    http.get("*/players/:id", () => HttpResponse.json(LAMB)),
    http.get("*/roster", () => HttpResponse.json([])),
    http.get("*/untouchables", () => HttpResponse.json({ player_ids: [] })),
  );

  return HtmlPlay.make(FixturesPanel, { competition: NFL, league: LEAGUE, route: Option.getOrThrow(AppRoute.parse(AT)) });
}

const opened = HtmlLocator.role("dialog", { name: "MIA at DAL" });

describe("the Fixtures page", () => {
  it.layer(page(AT), { buildPerTest: true })("a game", (it) => {
    it.effect("opens a game only where somebody's players are in it", () =>
      Effect.gen(function* () {
        const mine = game({ home: "DAL", yours: [{ player_id: "1", name: "Lamb", detail: "WR · starting" }] });

        const play = yield* scheduled([mine, game()]);

        yield* play.expect(Locator.text("Fixtures")).toExist();

        const rows = play.root.all(HtmlLocator.role("button", { name: /at/ }));

        assert.lengthOf(rows, 1);

        yield* play.click(HtmlLocator.role("button", { name: /MIA at DAL/ }));

        yield* play.expect(opened).toExist();
      }),
    );

    it.effect("swaps the game for one of its players, and his Back link swaps it back", () =>
      Effect.gen(function* () {
        const mine = game({ home: "DAL", yours: [{ player_id: "1", name: "Lamb", detail: "WR · starting" }] });

        const play = yield* scheduled([mine]);

        yield* play.click(HtmlLocator.role("button", { name: /MIA at DAL/ }));

        yield* play.click(Locator.inside(opened, HtmlLocator.role("button", { name: /Lamb/ })));

        const lamb = HtmlLocator.role("dialog", { name: "Lamb" });

        yield* play.expect(lamb).toExist();

        yield* play.expect(opened).toBeAbsent();

        yield* play.click(Locator.inside(lamb, HtmlLocator.role("button", { name: "MIA at DAL" })));

        yield* play.expect(opened).toExist();

        yield* play.expect(lamb).toBeAbsent();
      }),
    );
  });

  it.layer(page(AT), { buildPerTest: true })("paging through the season", (it) => {
    it.effect("reads the week shown from the summary, and steps the address a week at a time", () =>
      Effect.gen(function* () {
        const browsing = competitionOf({ key: "nfl-sleeper", browses_weeks: true });
        const weeks = { week: 11, current: 11, first: 1, last: 17 };
        const slate = (week: number): Slate => ({ games: [game({ label: `Week ${week}` })], byes: [], note: "" });

        server.use(
          // Only the summary's week range: the page reads nothing else of it, and the rest is the Matchup page's.
          http.get("*/week", () => HttpResponse.json({ weeks })),
          http.get("*/weeks/:week/games", ({ params }) => HttpResponse.json(slate(Number(params["week"])))),
        );

        const play = yield* HtmlPlay.make(FixturesPanel, {
          competition: browsing,
          league: LEAGUE,
          route: Option.getOrThrow(AppRoute.parse(AT)),
        });

        yield* play.expect(Locator.text("Week 11")).toExist();

        yield* play.click(HtmlLocator.role("button", { name: "Week 12" }));

        const router = yield* Router.Router;

        assert.strictEqual(router.location().url, "/nfl-sleeper/L1/fixtures?week=12");
      }),
    );
  });
});
