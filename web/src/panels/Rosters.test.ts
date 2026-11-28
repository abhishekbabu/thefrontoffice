import { Router } from "@effect/ui";
import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect } from "effect";
import { http, HttpResponse } from "msw";
import { AppRoute } from "@/lib/route";
import type { Competition, League, Outlook, PlayerCard, TeamRef } from "@/lib/types";
import { RostersPanel, askedTeam } from "@/panels/Rosters";
import { competitionOf } from "@/test/leagues";
import { page } from "@/test/play";
import { server } from "@/test/server";

const competition = competitionOf({ key: "nfl-sleeper", plans_weeks: false });
const PLANNING = { ...competition, plans_weeks: true };
const league: League = { league_id: "R1", name: "Sunday Money", detail: "", url: "" };

const teams: TeamRef[] = [
  { team_id: "1", name: "Me", detail: "6-4", url: "", is_mine: true },
  { team_id: "2", name: "Rival", detail: "3-7", url: "", is_mine: false },
];

const card = (id: string, name: string): PlayerCard => ({
  player_id: id,
  columns: { Player: name, Pos: "WR" },
  values: {},
  ruled_out: false,
  notes: {},
  tones: {},
  roles: { Player: "player" },
});

type Week = Outlook["weeks"][number];

const week = (n: number, more: Partial<Week> = {}): Week => ({
  week: n,
  points: 120,
  missing: [],
  short_by: 0,
  short: false,
  light: [],
  heavy: false,
  provisional: false,
  fix: "",
  gain: 0,
  ...more,
});

const NO_GRID = { run_weeks: [], runs: [], clear: 0, warnings: [] };

/** A league's teams and your roster, with the weeks ahead where the competition plans them. */
function rosters(mine: PlayerCard, outlook?: Outlook) {
  server.use(
    http.get("*/leagues/:league/teams", () => HttpResponse.json(teams)),
    http.get("*/leagues/:league/roster", () => HttpResponse.json([mine])),
    http.get("*/leagues/:league/untouchables", () => HttpResponse.json({ player_ids: ["u"] })),
    http.get("*/leagues/:league/outlook", () => HttpResponse.json(outlook ?? null)),
  );
}

/** The page at a league's roster, on `competition`. */
const opened = (at: Competition) =>
  Effect.gen(function* () {
    const route = yield* Router.currentRoute(AppRoute);

    return yield* HtmlPlay.make(RostersPanel, { competition: at, league, route });
  });

describe("Rosters", () => {
  it.layer(page("/nfl-sleeper/R1/rosters"), { buildPerTest: true })("a league's rosters", (it) => {
    it.effect("opens on yours and shows anybody else's from the chips", () =>
      Effect.gen(function* () {
        rosters(card("a", "Lamb"));

        server.use(http.get("*/teams/:team/roster", () => HttpResponse.json([card("b", "Nacua")])));

        const play = yield* opened(competition);

        assert.include(play.root.text(), "Lamb");

        // The record is the league table's; the card names the team and counts its players.
        assert.include(play.root.text(), "1 players");

        assert.notInclude(play.root.text(), "6-4");

        yield* play.click(HtmlLocator.role("button", { name: /Rival/ }));

        // The team is in the address, which the shell hands back as the route.
        const route = yield* Router.currentRoute(AppRoute);

        assert.strictEqual(askedTeam(route), "2");

        play.root.setProps({ competition, league, route });

        yield* play.expect(Locator.text("Nacua")).toExist();

        assert.notInclude(play.root.text(), "Lamb");
      }),
    );

    it.effect("lists only the weeks somebody misses", () =>
      Effect.gen(function* () {
        rosters(card("a", "Lamb"), {
          ...NO_GRID,
          usual: 120,
          measure: "proj",
          weeks: [week(12), week(13, { missing: ["Josh Allen (bye)"] }), week(14)],
        });

        const text = (yield* opened(PLANNING)).root.text();

        assert.include(text, "Week 13");

        assert.notInclude(text, "Week 12");

        assert.notInclude(text, "Week 14");
      }),
    );

    it.effect("says one line when nobody misses a week", () =>
      Effect.gen(function* () {
        rosters(card("a", "Lamb"), { ...NO_GRID, usual: 120, measure: "proj", weeks: [week(12), week(13), week(14)] });

        const text = (yield* opened(PLANNING)).root.text();

        assert.include(text, "through week 14");

        assert.notInclude(text, "Week 12");
      }),
    );

    it.effect("counts a basketball week in games, and lists a light or heavy one with its stream", () =>
      Effect.gen(function* () {
        rosters(card("a", "Brunson"), {
          usual: 40.5,
          ...NO_GRID,
          measure: "games",
          weeks: [
            week(6, { points: 40 }),
            week(7, { points: 34, short: true, short_by: 6.5, light: ["Jalen Brunson (2 games)"] }),
            week(8, { points: 40, heavy: true, fix: "Pick up Kris Dunn (PG, LAC, 4 games), drop Coby White (2 games)", gain: 2 }),
            week(9, { points: 40, provisional: true }),
          ],
        });

        const text = (yield* opened(PLANNING)).root.text();

        assert.notInclude(text, "Week 6");

        assert.include(text, "34 games");

        assert.include(text, "Jalen Brunson (2 games)");

        assert.include(text, "heavy");

        assert.include(text, "Kris Dunn");

        assert.include(text, "+2 games");

        assert.include(text, "Week 9");

        assert.include(text, "provisional");
      }),
    );

    it.effect("shows FPL's weeks ahead as a fixture grid of only the players to watch", () =>
      Effect.gen(function* () {
        const fpl = competitionOf({ key: "premier-league-fpl", plans_weeks: true });

        rosters(card("a", "Haaland"), {
          usual: null,
          measure: "proj",
          weeks: [],
          run_weeks: [11, 12],
          runs: [
            {
              player_id: "a",
              player: "Haaland",
              detail: "FWD · MCI",
              weeks: [
                { week: 11, games: [{ opponent: "ARS", home: false, difficulty: 5 }] },
                { week: 12, games: [] },
              ],
              flags: ["blank GW12"],
            },
          ],
          clear: 14,
          warnings: [{ label: "GW12", value: "1 blank: Haaland", tone: "warning", url: "", better: null, hint: "" }],
        });

        const text = (yield* opened(fpl)).root.text();

        assert.include(text, "1 to watch");

        assert.include(text, "ARS A 5");

        assert.include(text, "blank GW12");

        assert.include(text, "1 blank: Haaland");

        assert.include(text, "14 others");
      }),
    );

    it.effect("carries a lock on each of yours marked untouchable", () =>
      Effect.gen(function* () {
        rosters(card("u", "Tyson"));

        const play = yield* opened(competition);

        assert.lengthOf(play.root.all(Locator.attr("aria-label", "Untouchable")), 1);
      }),
    );
  });
});
