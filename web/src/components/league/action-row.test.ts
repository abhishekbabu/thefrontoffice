import { HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, it } from "@effect/vitest";
import { Effect } from "effect";
import { Compared } from "@/components/league/action-row";
import type { MovePlayer } from "@/lib/types";
import { page, showing } from "@/test/play";

const valued = (name: string): MovePlayer => ({
  side: "in",
  player_id: name,
  name,
  position: "PG",
  team: "BOS",
  held: "free agent",
  figures: [
    { label: "Cat value/g", value: "1.2", tone: "neutral", url: "", better: null, hint: "A game's worth across the categories." },
    { label: "Weak in", value: "FG% .380", tone: "neutral", url: "", better: null, hint: "" },
  ],
});

it.layer(page(), { buildPerTest: true })("players compared", (it) => {
  it.effect("lets a figure that is the app's own measure explain itself, and leaves the league's plain", () =>
    Effect.gen(function* () {
      const play = yield* HtmlPlay.make(
        showing((h) => Compared(h, { key: "swap", players: [valued("A"), valued("B")] })),
        {},
      );

      const explained = play.root.all(Locator.attr("aria-label")).map((node) => node.attrs?.["aria-label"]);

      assert.deepStrictEqual(explained, ["Cat value/g: A game's worth across the categories."]);

      assert.include(play.root.text(), "Weak inFG% .380FG% .380");
    }),
  );
});
