import { HtmlLocator, HtmlScene } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect } from "effect";
import { LoadingBar } from "@/components/ui/progress";
import { showing } from "@/test/play";

const roster = showing((h) => LoadingBar(h, { label: "Loading roster" }));

describe("LoadingBar", () => {
  it.effect("is an indeterminate progress bar, named for what it waits on", () =>
    Effect.gen(function* () {
      const s = yield* HtmlScene.make(roster, {});

      const { attrs } = s.get(HtmlLocator.role("progressbar", { name: "Loading roster" }));

      // No true progress is known, so it claims none.
      assert.notProperty(attrs, "aria-valuenow");
    }),
  );

  it.effect("carries its state in visible text too, not only in the moving bar", () =>
    Effect.gen(function* () {
      const s = yield* HtmlScene.make(roster, {});

      assert.include(Locator.textOf(s.root), "Loading roster");
    }),
  );
});
