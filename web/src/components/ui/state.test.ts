import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, it } from "@effect/vitest";
import { Effect } from "effect";
import { AsyncResult } from "effect/reactivity";
import { QueryState } from "@/components/ui/state";
import { ApiError } from "@/lib/api";
import { page, showing } from "@/test/play";

const asked = AsyncResult.initial<string, ApiError>(true);
const answered = AsyncResult.success<string, ApiError>("roster");
const failed = AsyncResult.fail(new ApiError({ message: "Yahoo is down", code: "error", remedy: null }));

const status = HtmlLocator.role("status");
const bar = HtmlLocator.role("progressbar");

it.layer(page(), { buildPerTest: true })("QueryState", (it) => {
  it.effect("shows a progress bar in a polite status region while the query is asked", () =>
    Effect.gen(function* () {
      const play = yield* HtmlPlay.make(showing((h) => h.div(QueryState(h, asked))), {});

      yield* play.expect(status).toHaveAttribute("aria-live", "polite");

      yield* play.expect(Locator.inside(status, bar)).toExist();
    }),
  );

  it.effect("holds more room open for a page with more rows coming", () =>
    Effect.gen(function* () {
      const height = (lines: number) =>
        Effect.gen(function* () {
          const play = yield* HtmlPlay.make(showing((h) => h.div(QueryState(h, asked, { lines }))), {});

          return parseFloat(/min-height:\s*([\d.]+)/.exec(play.root.get(status).attrs?.style ?? "")?.[1] ?? "");
        });

      assert.isAbove(yield* height(6), yield* height(2));
    }),
  );

  it.effect("shows the failure instead once the query fails", () =>
    Effect.gen(function* () {
      const play = yield* HtmlPlay.make(showing((h) => h.div(QueryState(h, failed))), {});

      yield* play.expect(bar).toBeAbsent();

      assert.include(play.root.text(), "Yahoo is down");
    }),
  );

  it.effect("renders nothing once the answer is in", () =>
    Effect.gen(function* () {
      const play = yield* HtmlPlay.make(showing((h) => h.div(QueryState(h, answered))), {});

      yield* play.expect(bar).toBeAbsent();

      assert.strictEqual(play.root.text(), "");
    }),
  );
});
