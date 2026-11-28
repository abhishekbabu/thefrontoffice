import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect } from "effect";
import { http, HttpResponse } from "msw";
import { Drawers, playerDrawer, type DrawerState } from "@/components/league/drawers";
import type { PlayerCard, PlayerDetail } from "@/lib/types";
import { competitionOf, leagueOf } from "@/test/leagues";
import { page } from "@/test/play";
import { playerDetail } from "@/test/players";
import { server } from "@/test/server";

const NFL = competitionOf({ key: "nfl-sleeper" });
const LEAGUE = leagueOf("900");

const ALLEN: PlayerDetail = playerDetail({
  player_id: "17",
  name: "Josh Allen",
  position: "QB",
  team: "BUF",
  team_name: "Buffalo Bills",
  headline: "24.1",
  headline_label: "proj pts",
});

/** Him as a row of your roster. */
const ALLEN_CARD: PlayerCard = {
  player_id: ALLEN.player_id,
  columns: { Player: ALLEN.name },
  values: {},
  ruled_out: false,
  notes: {},
  tones: {},
  roles: { Player: "player" },
};

const PROJECTED = { label: "Projected", value: "24.1", tone: "neutral", url: "", better: null, hint: "" } as const;

const drawer = HtmlLocator.role("dialog", { name: "Josh Allen" });

/** The server, answering for his drawer on `detail`, each of `tabs` its own read, and `roster` as yours. */
function answering(detail: PlayerDetail, tabs: Record<string, PlayerDetail> = {}, roster: PlayerCard[] = []) {
  server.use(
    http.get("*/players/:id/tabs/:tab", ({ params }) => HttpResponse.json(tabs[String(params["tab"])])),
    http.get("*/players/:id", () => HttpResponse.json(detail)),
    http.get("*/roster", () => HttpResponse.json(roster)),
    http.get("*/untouchables", () => HttpResponse.json({ player_ids: [] })),
  );
}

/** His drawer, open as the page opened it. */
const opened = (open: DrawerState = playerDrawer(ALLEN.player_id)) =>
  HtmlPlay.make(Drawers, { competition: NFL.key, league: LEAGUE.league_id, open });

describe("the player drawer", () => {
  it.layer(page(), { buildPerTest: true })("reading him", (it) => {
    it.effect("shows one tab at a time, offers only tabs with something in them, and names his owner", () =>
      Effect.gen(function* () {
        answering({
          ...ALLEN,
          owner: "Rival",
          tabs: ["This week", "History", "News"],
          groups: [
            { title: "Week 11", tab: "", note: "", stats: [PROJECTED] },
            {
              title: "Moves",
              tab: "History",
              note: "",
              stats: [{ label: "Draft", value: "Round 1", tone: "neutral", url: "", better: null, hint: "" }],
            },
            { title: "Latest news", tab: "News", note: "", stats: [] },
          ],
        });

        const play = yield* opened();

        const tabs = play.root.all(Locator.inside(drawer, HtmlLocator.role("tab"))).map(Locator.textOf);

        assert.deepStrictEqual(tabs, ["This week", "History"]);

        yield* play.expect(Locator.inside(drawer, Locator.text("Rival"))).toExist();

        yield* play.expect(Locator.inside(drawer, Locator.text("Projected"))).toExist();

        yield* play.expect(Locator.inside(drawer, Locator.text("Round 1"))).toBeAbsent();

        yield* play.click(HtmlLocator.role("tab", { name: "History" }));

        yield* play.expect(Locator.inside(drawer, Locator.text("Round 1"))).toExist();

        yield* play.expect(Locator.inside(drawer, Locator.text("Projected"))).toBeAbsent();
      }),
    );

    it.effect("sets each fact under his name as its label over its value, and his status in words", () =>
      Effect.gen(function* () {
        answering({ ...ALLEN, rank: "QB3", owner: "Rival", note: "Questionable", tone: "warning" });

        const play = yield* opened();

        assert.deepStrictEqual(facts(play.root), { "proj pts": "24.1", "Pos rank": "QB3", Owner: "Rival" });

        yield* play.expect(Locator.inside(drawer, Locator.text("Questionable"))).toExist();
      }),
    );

    it.effect("says why there is no figure, and shows only the facts he has", () =>
      Effect.gen(function* () {
        answering({ ...ALLEN, headline: "", headline_label: "Not projected in week 11", owner: "Free agent" });

        const play = yield* opened();

        assert.deepStrictEqual(facts(play.root), { Owner: "Free agent" });

        yield* play.expect(Locator.inside(drawer, Locator.text("Not projected in week 11"))).toExist();
      }),
    );

    it.effect("offers a deferred tab before it is read, and shows what its own read holds once opened", () =>
      Effect.gen(function* () {
        const seasons = playerDetail({
          ...ALLEN,
          tables: [
            {
              title: "By season",
              tab: "Seasons",
              columns: ["2025-26"],
              rows: [{ label: "PTS", values: ["14.8"], tone: "neutral", better: "higher", best: [] }],
              absent: "N/A",
            },
          ],
        });

        answering(
          playerDetail({
            ...ALLEN,
            tabs: ["This week", "Seasons", "News"],
            deferred: ["Seasons", "News"],
            groups: [{ title: "Week 11", tab: "", note: "", stats: [PROJECTED] }],
          }),
          { Seasons: seasons, News: playerDetail({ ...ALLEN }) },
        );

        const play = yield* opened();

        const tabs = play.root.all(Locator.inside(drawer, HtmlLocator.role("tab"))).map(Locator.textOf);

        assert.deepStrictEqual(tabs, ["This week", "Seasons", "News"]);

        yield* play.click(HtmlLocator.role("tab", { name: "Seasons" }));

        yield* play.expect(Locator.inside(drawer, Locator.text("2025-26"))).toExist();

        yield* play.expect(Locator.inside(drawer, Locator.text("Projected"))).toBeAbsent();

        yield* play.click(HtmlLocator.role("tab", { name: "News" }));

        yield* play.expect(Locator.inside(drawer, Locator.text("No news on record."))).toExist();
      }),
    );
  });

  it.layer(page(), { buildPerTest: true })("his history", (it) => {
    it.effect("opens a move on his history the way Activity does", () =>
      Effect.gen(function* () {
        answering(
          playerDetail({
            ...ALLEN,
            tabs: ["This week", "History"],
            moves_tab: "History",
            groups: [{ title: "Week 11", tab: "", note: "", stats: [PROJECTED] }],
            moves: [
              {
                when: "19 Sep",
                who: "Rival ↔ Me",
                what: "Trade",
                detail: "+Josh Allen · +Bad RB",
                is_mine: true,
                bid: "",
                moves: [
                  { player_id: "17", player: "Josh Allen", position: "QB", team: "BUF", change: "added", manager: "Me" },
                  { player_id: "rb2", player: "Bad RB", position: "RB", team: "MIA", change: "added", manager: "Rival" },
                ],
              },
            ],
          }),
        );

        const play = yield* opened();

        yield* play.click(HtmlLocator.role("tab", { name: "History" }));

        yield* play.click(Locator.inside(drawer, HtmlLocator.role("button", { name: /Trade/ })));

        const asked = play.root.emitted.at(-1);

        assert.strictEqual(asked?._tag === "RequestedOpen" && asked.open.kind, "move");

        if (asked?._tag !== "RequestedOpen") return;

        play.root.setProps({ competition: NFL.key, league: LEAGUE.league_id, open: asked.open });

        yield* play.expect(
          Locator.inside(HtmlLocator.role("dialog", { name: "Trade by Rival ↔ Me" }), Locator.text("To Rival")),
        ).toExist();
      }),
    );
  });

  it.layer(page(), { buildPerTest: true })("untouchable", (it) => {
    it.effect("offers no untouchable mark on a player who is not yours", () =>
      Effect.gen(function* () {
        answering(ALLEN);

        const play = yield* opened();

        yield* play.expect(drawer).toExist();

        yield* play.expect(HtmlLocator.role("button", { name: "Mark untouchable" })).toBeAbsent();
      }),
    );

    it.effect("marks one of yours untouchable on the server, and the lock and its name say so", () =>
      Effect.gen(function* () {
        const sent: unknown[] = [];

        answering(ALLEN, {}, [ALLEN_CARD]);

        server.use(
          http.post("*/untouchables", async ({ request }) => {
            sent.push(await request.json());

            return HttpResponse.json({ player_ids: [ALLEN.player_id] });
          }),
        );

        const play = yield* opened();

        yield* play.click(HtmlLocator.role("button", { name: "Mark untouchable" }));

        assert.deepStrictEqual(sent, [{ player_id: ALLEN.player_id, untouchable: true }]);

        yield* play.expect(HtmlLocator.role("button", { name: "Untouchable: clear" })).toHaveAttribute("aria-pressed", "true");
      }),
    );
  });
});

/** The facts under his name, each label to its value: the first list in the drawer, its header's. */
function facts(root: { all: (locator: Locator.Locator) => ReadonlyArray<Locator.Node> }): Record<string, string> {
  const terms = root.all(Locator.inside(drawer, Locator.tag("dt"))).map(Locator.textOf);
  const values = root.all(Locator.inside(drawer, Locator.tag("dd"))).map(Locator.textOf);

  return Object.fromEntries(terms.map((term, i) => [term, values[i] ?? ""]));
}
