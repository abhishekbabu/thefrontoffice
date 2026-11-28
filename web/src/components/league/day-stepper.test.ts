import { Router, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { HtmlLocator, HtmlPlay, TestGlobalEvents } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect, Layer, Schema } from "effect";
import { DayStepper, dayAsked, stepDay, type DayRange } from "@/components/league/day-stepper";
import { AppRoute } from "@/lib/route";
import { page } from "@/test/play";

const week = (day: string, today: string | null = "2026-11-24"): DayRange => ({
  day,
  first: "2026-11-23",
  last: "2026-11-29",
  today,
});

const button = (name: string) => HtmlLocator.role("button", { name });

/** The days a stepper asked for, in order. */
const asked = (emitted: ReadonlyArray<{ day: string }>) => emitted.map((event) => event.day);

describe("DayStepper", () => {
  it.layer(Layer.merge(page(), TestGlobalEvents.layer), { buildPerTest: true })("stepping", (it) => {
    it.effect("names the day each arrow goes to, and steps to it", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(DayStepper, { range: week("2026-11-25") });

        yield* play.click(button("Tue 24 Nov"));

        yield* play.click(button("Thu 26 Nov"));

        yield* play.expect(Locator.attr("aria-live")).toHaveText("Wed 25 Nov");

        assert.deepStrictEqual(asked(play.root.emitted), ["2026-11-24", "2026-11-26"]);
      }),
    );

    it.effect("says today is today, and offers the way back to it from any other day of its week", () =>
      Effect.gen(function* () {
        const here = yield* HtmlPlay.make(DayStepper, { range: week("2026-11-24") });

        assert.include(here.root.text(), "today");

        yield* here.expect(button("Back to today (Tue 24 Nov)")).toBeAbsent();

        const away = yield* HtmlPlay.make(DayStepper, { range: week("2026-11-28") });

        yield* away.click(button("Back to today (Tue 24 Nov)"));

        assert.deepStrictEqual(asked(away.root.emitted), ["2026-11-24"]);
      }),
    );

    it.effect("offers no way back to today from a week that does not hold it", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(DayStepper, { range: week("2026-11-23", null) });

        yield* play.expect(HtmlLocator.role("button", { name: /^Back to today/ })).toBeAbsent();

        assert.notInclude(play.root.text(), "today");
      }),
    );

    it.effect("goes no further than the week does, by arrow or by key", () =>
      Effect.gen(function* () {
        const first = yield* HtmlPlay.make(DayStepper, { range: week("2026-11-23") });

        yield* first.expect(button("Sun 22 Nov")).toHaveAttribute("disabled");

        yield* TestGlobalEvents.fire("document", "keydown", { key: "ArrowLeft" });

        yield* first.expect(button("Tue 24 Nov")).toExist();

        assert.deepStrictEqual(asked(first.root.emitted), []);
      }),
    );

    it.effect("steps back a day by key from the end of the week, where it cannot step on", () =>
      Effect.gen(function* () {
        const last = yield* HtmlPlay.make(DayStepper, { range: week("2026-11-29") });

        yield* last.expect(button("Mon 30 Nov")).toHaveAttribute("disabled");

        yield* TestGlobalEvents.fire("document", "keydown", { key: "ArrowLeft" });

        yield* TestGlobalEvents.fire("document", "keydown", { key: "ArrowRight" });

        yield* last.expect(button("Sat 28 Nov")).toExist();

        assert.deepStrictEqual(asked(last.root.emitted), ["2026-11-28"]);
      }),
    );
  });
});

const StepMessage = UiSchema.TaggedEnum({ ClickedStep: {} });

/** A page that steps its address to a day, as a panel does from its stepper. */
const Stepping = Html.component({
  name: "Stepping",
  props: Schema.Struct({ route: AppRoute, range: Schema.Struct({ day: Schema.String, today: Schema.NullOr(Schema.String) }), to: Schema.String }),
  model: Schema.Null,
  message: StepMessage,
}).make({
  init: () => null,
  update: {
    ClickedStep: ($) =>
      $.run(stepDay($.props.route, week($.props.range.day, $.props.range.today), $.props.to)),
  },
  view: (h) => h.button.attr("type", "button").on("click", StepMessage.ClickedStep()).children("step"),
});

const stepping = (day: string, to: string) =>
  Effect.map(Router.props(AppRoute), ({ route }) => ({ route, range: { day, today: "2026-11-24" }, to }));

describe("stepDay", () => {
  it.layer(page("/nba-yahoo/1?week=3"), { buildPerTest: true })("from the week's own address", (it) => {
    it.effect("names a day in the address beside the week, as a history entry", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Stepping, stepping("2026-11-24", "2026-11-26"));

        yield* play.click("step");

        const router = yield* Router.Router;

        assert.strictEqual(router.location().url, "/nba-yahoo/1?week=3&day=2026-11-26");

        assert.strictEqual(router.location().action, "push");
      }),
    );
  });

  it.layer(page("/nba-yahoo/1?week=3&day=2026-11-26"), { buildPerTest: true })("from another day", (it) => {
    it.effect("leaves off the day the week opens on", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Stepping, stepping("2026-11-26", "2026-11-24"));

        yield* play.click("step");

        const router = yield* Router.Router;

        assert.strictEqual(router.location().url, "/nba-yahoo/1?week=3");
      }),
    );
  });
});

describe("dayAsked", () => {
  const league = (day: string | undefined) =>
    AppRoute.League({ params: { competition: "nba-yahoo", league: "1" }, search: day === undefined ? {} : { day } });

  it("reads the day the address names, and nothing that is not a day", () => {
    assert.strictEqual(dayAsked(league("2026-11-26")), "2026-11-26");

    assert.strictEqual(dayAsked(league("tomorrow")), null);

    assert.strictEqual(dayAsked(league(undefined)), null);

    assert.strictEqual(dayAsked(AppRoute.Settings()), null);
  });
});
