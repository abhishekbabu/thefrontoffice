import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, it } from "@effect/vitest";
import { Effect } from "effect";
import { IconButton, IconButtonEvents } from "@/components/ui/controls/icon-button";
import { page } from "@/test/play";

it.layer(page(), { buildPerTest: true })("an icon button", (it) => {
  it.effect("is named by its label and says it was pressed", () =>
    Effect.gen(function* () {
      const play = yield* HtmlPlay.make(IconButton, { label: "Close", icon: "x" });

      yield* play.click(HtmlLocator.role("button", { name: "Close" }));

      assert.deepStrictEqual(play.root.emitted, [IconButtonEvents.Clicked()]);
    }),
  );

  it.effect("shows its label as a tooltip on keyboard focus", () =>
    Effect.gen(function* () {
      const play = yield* HtmlPlay.make(IconButton, { label: "Close", icon: "x" });

      yield* play.expect(Locator.attr("data-open")).toBeAbsent();

      yield* play.fire(HtmlLocator.role("button", { name: "Close" }), "focus", { focusVisible: true });

      yield* play.expect(Locator.inside(Locator.attr("data-open"), Locator.text("Close"))).toExist();
    }),
  );
});
