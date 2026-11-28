import { HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, it } from "@effect/vitest";
import { Effect } from "effect";
import { Categories } from "@/components/league/categories";
import type { CategoryLine } from "@/lib/types";
import { page, showing } from "@/test/play";

/** The card as the matchup draws it, and the text of each category's row. */
function categories(lines: CategoryLine[]) {
  return Effect.gen(function* () {
    const play = yield* HtmlPlay.make(showing((h) => Categories(h, { lines })), {});

    const rows = play.root.all(Locator.inside(Locator.tag("tbody"), Locator.tag("tr"))).map((row) => Locator.textOf(row));

    const head = play.root.all(Locator.tag("thead")).map((row) => Locator.textOf(row));

    return { play, rows, head };
  });
}

it.layer(page(), { buildPerTest: true })("Categories", (it) => {
  it.effect("says who leads each category in words, and a dash where nobody does yet", () =>
    Effect.gen(function* () {
      const { play, rows, head } = yield* categories([
        { name: "PTS", mine: "520", theirs: "498", lead: "mine", win: null },
        { name: "BLK", mine: "12", theirs: "17", lead: "theirs", win: null },
        { name: "TO", mine: "-", theirs: "-", lead: null, win: null },
      ]);

      assert.match(rows.find((r) => r.startsWith("PTS")) ?? "", /You$/);

      assert.match(rows.find((r) => r.startsWith("BLK")) ?? "", /Them$/);

      assert.match(rows.find((r) => r.startsWith("TO")) ?? "", /—$/);

      assert.notInclude(play.root.text(), "Win");

      // The heading says "Them" rather than a name the column truncates.
      assert.deepStrictEqual(head, ["CatYouThemLeads"]);
    }),
  );

  it.effect("gives each category's chance of winning where the week is forecast", () =>
    Effect.gen(function* () {
      const { rows } = yield* categories([
        { name: "PTS", mine: "520", theirs: "498", lead: "mine", win: 0.734 },
        { name: "DD", mine: "1", theirs: "0", lead: "mine", win: null },
      ]);

      assert.match(rows.find((r) => r.startsWith("PTS")) ?? "", /You73%$/);

      assert.match(rows.find((r) => r.startsWith("DD")) ?? "", /You—$/);
    }),
  );
});
