import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect, Option } from "effect";
import { http, HttpResponse } from "msw";
import { AppRoute } from "@/lib/route";
import type { LeagueSchedule, PlayerDetail } from "@/lib/types";
import { ActivityPanel } from "@/panels/Activity";
import { competitionOf, leagueOf } from "@/test/leagues";
import { page } from "@/test/play";
import { playerDetail } from "@/test/players";
import { server } from "@/test/server";

const competition = competitionOf({ key: "nfl-sleeper", finds_trades: true });
const league = { ...leagueOf("L1"), name: "Sunday Money" };
const AT = "/nfl-sleeper/L1/activity";

const schedule: LeagueSchedule = {
  headline: [],
  season: [],
  standings: [],
  matches: [],
  activity: [
    {
      when: "16 Nov",
      who: "Rival ↔ Me",
      what: "Trade",
      detail: "+Star QB, $5 FAAB · +Bad RB",
      is_mine: false,
      bid: "",
      moves: [
        { player_id: "qb1", player: "Star QB", position: "QB", team: "BUF", change: "added", manager: "Rival" },
        { player_id: "", player: "$5 FAAB", position: "", team: "", change: "added", manager: "Rival" },
        { player_id: "rb2", player: "Bad RB", position: "RB", team: "MIA", change: "added", manager: "Me" },
        { player_id: "rb2", player: "Bad RB", position: "RB", team: "MIA", change: "dropped", manager: "Rival" },
        { player_id: "qb1", player: "Star QB", position: "QB", team: "BUF", change: "dropped", manager: "Me" },
      ],
    },
  ],
};

const STAR_QB: PlayerDetail = playerDetail({ player_id: "qb1", name: "Star QB", position: "QB", team: "BUF" });

const trade = HtmlLocator.role("dialog", { name: "Trade by Rival ↔ Me" });
const star = HtmlLocator.role("dialog", { name: "Star QB" });

describe("League activity", () => {
  it.layer(page(AT), { buildPerTest: true })("a move", (it) => {
    it.effect("opens a trade in full, by who got whom", () =>
      Effect.gen(function* () {
        server.use(
          http.get("*/season", () => HttpResponse.json(schedule)),
          http.get("*/players/:id", () => HttpResponse.json(STAR_QB)),
          http.get("*/roster", () => HttpResponse.json([])),
          http.get("*/untouchables", () => HttpResponse.json({ player_ids: [] })),
        );

        const route = Option.getOrThrow(AppRoute.parse(AT));
        const play = yield* HtmlPlay.make(ActivityPanel, { competition, league, route });

        yield* play.click(HtmlLocator.role("button", { name: /Star QB/ }));

        yield* play.expect(trade).toExist();

        const text = play.root.all(trade).map(Locator.textOf).join("");

        assert.match(text, /To Rival.*Star QB.*\$5 FAAB/);

        assert.include(text, "To Me");

        assert.include(text, "QB · BUF");

        // A player opened from the move takes its place, with the way back to it.
        yield* play.click(Locator.inside(trade, HtmlLocator.role("button", { name: /Star QB/ })));

        yield* play.expect(star).toExist();

        yield* play.expect(trade).toBeAbsent();

        yield* play.click(Locator.inside(star, HtmlLocator.role("button", { name: "Trade · Rival ↔ Me" })));

        yield* play.expect(trade).toExist();
      }),
    );
  });
});
