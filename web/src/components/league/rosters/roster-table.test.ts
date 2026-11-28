import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect } from "effect";
import { RosterTable, toOrder } from "@/components/league/rosters/roster-table";
import type { PlayerCard } from "@/lib/types";
import { page, showing } from "@/test/play";

const card = (id: string, without: string, notes: Record<string, string> = {}): PlayerCard => ({
  player_id: id,
  columns: { Player: id, Without: without },
  values: {},
  ruled_out: false,
  notes,
  tones: {},
  roles: { Player: "player" },
});

/** The table of `players`, sortable and unsorted, on a page of its own. */
const table = (players: PlayerCard[], hints?: Record<string, string>) =>
  HtmlPlay.make(
    showing((h) => RosterTable(h, { players, empty: { title: "Nobody" }, sort: null, onSort: unsorted, hints })),
    {},
  );

/** A page that holds no sort has no message for one: no test here clicks a heading. */
function unsorted(): never {
  throw new Error("no test sorts this table");
}

const classes = (node: Locator.Node) => (node.attrs?.class ?? "").split(" ");

/** What a screen reader hears of every cell that explains itself on focus: a focusable button carrying its note. */
const noted = (play: Effect.Success<ReturnType<typeof table>>) =>
  play.root
    .all(Locator.inside(Locator.tag("td"), Locator.attr("aria-label")))
    .map((node) => node.attrs?.["aria-label"]);

describe("RosterTable", () => {
  it.layer(page(), { buildPerTest: true })("a roster", (it) => {
    it.effect("says what a column measures on its heading", () =>
      Effect.gen(function* () {
        const hints = { Without: "Points a game with a teammate out" };

        const play = yield* table([card("Mayer", "—")], hints);

        yield* play.expect(HtmlLocator.role("button", { name: /^Points a game with a teammate out\. Sort by Without/ })).toExist();
      }),
    );

    it.effect("aligns a column with a role as words, though a number sorts it", () =>
      Effect.gen(function* () {
        const row: PlayerCard = {
          ...card("Barner", "—"),
          columns: { Player: "Barner", Opponent: "vs SF, easiest", Proj: "7.39" },
          values: { Opponent: 1.1, Proj: 7.39 },
          roles: { Player: "player", Opponent: "opponent" },
        };

        const play = yield* table([row]);

        const aligned = play.root
          .all(Locator.tag("td"))
          .filter((td) => classes(td).includes("text-right"))
          .map((td) => Locator.textOf(td));

        assert.deepStrictEqual(aligned, ["7.39"]);
      }),
    );

    it.effect("colors a toned cell by its tone, its text unchanged", () =>
      Effect.gen(function* () {
        const soft: PlayerCard = { ...card("Barner", "—"), tones: { Without: "good" } };

        const play = yield* table([soft, card("Kelce", "—")]);

        const toned = play.root
          .all(Locator.tag("span"))
          .filter((span) => classes(span).includes("text-ok"))
          .map((span) => Locator.textOf(span));

        assert.deepStrictEqual(toned, ["—"]);
      }),
    );

    it.effect("gives an abbreviated cell its full reading, reachable by keyboard, and leaves the rest plain", () =>
      Effect.gen(function* () {
        const note = "Without Brock Bowers (TE, Q): 6.10/game in 3 games · 8.60 with";

        const play = yield* table([card("Mayer", "Bowers Q", { Without: note }), card("Kelce", "—")]);

        assert.deepStrictEqual(noted(play), [`Bowers Q: ${note}`]);

        yield* play.expect(HtmlLocator.role("button", { name: `Bowers Q: ${note}` })).toExist();

        assert.include(play.root.text(), "—");
      }),
    );

    it.effect("gives a status badge its fuller reading, and leaves one without a note a plain badge", () =>
      Effect.gen(function* () {
        const status = (id: string, value: string, notes: Record<string, string> = {}): PlayerCard => ({
          ...card(id, "—", notes),
          columns: { Player: id, Status: value },
          roles: { Player: "player", Status: "status" },
        });

        const play = yield* table([status("Curry", "O", { Status: "back ~22 Nov" }), status("Butler", "GTD")]);

        assert.deepStrictEqual(noted(play), ["O: back ~22 Nov"]);

        assert.include(play.root.text(), "GTD");
      }),
    );
  });
});

describe("toOrder", () => {
  it("asks for no column where none is sorted, so the competition's own order is one entry", () => {
    assert.deepStrictEqual(toOrder(null), {});

    assert.deepStrictEqual(toOrder({ column: "Proj", descending: false }), { sort: "Proj", descending: false });
  });
});
