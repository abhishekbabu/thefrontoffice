import { HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, it } from "@effect/vitest";
import { Effect } from "effect";
import { DataTable } from "@/components/ui/data-table";
import { page, showing } from "@/test/play";

it.layer(page(), { buildPerTest: true })("DataTable", (it) => {
  it.effect("says what a column measures on a heading that does not sort, reachable by keyboard", () =>
    Effect.gen(function* () {
      const rows = [{ player_id: "1", columns: { Player: "Lopez", Rost: "44%" } }];

      const play = yield* HtmlPlay.make(
        showing((h) => DataTable(h, { rows, hints: { Rost: "% rostered across Yahoo leagues" } })),
        {},
      );

      // A heading is reachable when it holds a control: the hint's button.
      const focusable = play.root
        .all(Locator.tag("th"))
        .map((th) => Locator.query(th, Locator.tag("button")))
        .map((button) => button && Locator.textOf(button));

      assert.deepStrictEqual(focusable, [undefined, "Rost"]);
    }),
  );
});
