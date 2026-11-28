import { Router, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { HtmlLocator, HtmlPlay, TestGlobalEvents } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect, Layer, Schema } from "effect";
import { SWIPE_DISTANCE, WeekPane, WeekStepper, stepWeek, weekShown } from "@/components/league/week-stepper";
import { AppRoute } from "@/lib/route";
import type { WeekRange } from "@/lib/types";
import { page } from "@/test/play";

/** A page holding a week's pane, its week and whether it is still loading set from outside, as a panel's query would. */
const Holding = Html.component({
  name: "Holding",
  props: Schema.Struct({ week: Schema.Number, pending: Schema.Boolean }),
  model: Schema.Null,
  message: Schema.Never,
}).make({
  init: () => null,
  update: ($) => $.model,
  view: (h) =>
    WeekPane(h, {
      props: { week: h.props.week, pending: h.props.pending },
      slots: { content: h.p(`week ${h.props.week}`) },
    }),
});

const pane = Locator.attr("data-week");

describe("WeekPane", () => {
  it.layer(page(), { buildPerTest: true })("stepping", (it) => {
    it.effect("holds the week it shows while the next is still loading, and changes once it arrives", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Holding, { week: 3, pending: false });

        yield* play.expect(pane).toHaveAttribute("data-week", "3");

        // The page keeps the last week's pane up while the next loads.
        play.root.setProps({ week: 4, pending: true });

        yield* play.expect(pane).toHaveAttribute("data-week", "3");

        play.root.setProps({ week: 4, pending: false });

        yield* play.expect(pane).toHaveAttribute("data-week", "4");

        assert.strictEqual(play.root.text(), "week 4");
      }),
    );
  });
});

const range = (week: number): WeekRange => ({ week, current: 10, first: 1, last: 16 });

const button = (name: string) => HtmlLocator.role("button", { name });

/** The weeks a stepper asked for, in order. */
const asked = (emitted: ReadonlyArray<{ week: number }>) => emitted.map((event) => event.week);

describe("WeekStepper", () => {
  it.layer(Layer.merge(page(), TestGlobalEvents.layer), { buildPerTest: true })("stepping", (it) => {
    it.effect("names the week each arrow goes to, and steps to it", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(WeekStepper, { range: range(10) });

        yield* play.click(button("Week 9"));

        yield* play.click(button("Week 11"));

        assert.deepStrictEqual(asked(play.root.emitted), [9, 11]);
      }),
    );

    it.effect("says the week being played is this week, and offers the way back from any other", () =>
      Effect.gen(function* () {
        const here = yield* HtmlPlay.make(WeekStepper, { range: range(10) });

        assert.include(here.root.text(), "this week");

        const away = yield* HtmlPlay.make(WeekStepper, { range: range(4) });

        yield* away.click(button("Back to this week (week 10)"));

        assert.deepStrictEqual(asked(away.root.emitted), [10]);
      }),
    );

    it.effect("calls the week what the competition calls it", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(WeekStepper, { range: range(4), word: "gameweek" });

        yield* play.expect(Locator.attr("aria-live")).toHaveText("Gameweek 4");

        yield* play.expect(button("Gameweek 5")).toExist();

        yield* play.expect(button("Back to this gameweek (gameweek 10)")).toExist();

        assert.notMatch(play.root.text(), /\bweek\b/i);
      }),
    );

    it.effect("goes no further than the season does", () =>
      Effect.gen(function* () {
        const start = yield* HtmlPlay.make(WeekStepper, { range: range(1) });

        yield* start.expect(button("Week 0")).toHaveAttribute("disabled");

        const end = yield* HtmlPlay.make(WeekStepper, { range: range(16) });

        yield* end.expect(button("Week 17")).toHaveAttribute("disabled");
      }),
    );

    it.effect("steps with the arrow keys, but not while something is being typed", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(WeekStepper, { range: range(10) });

        yield* TestGlobalEvents.fire("document", "keydown", { key: "ArrowLeft" });

        yield* TestGlobalEvents.fire("document", "keydown", { key: "ArrowRight", editable: true });

        yield* play.expect(button("Week 9")).toExist();

        assert.deepStrictEqual(asked(play.root.emitted), [9]);
      }),
    );

    it.effect("leaves the arrow keys to a finer stepper beside it", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(WeekStepper, { range: range(10), keys: false });

        yield* TestGlobalEvents.fire("document", "keydown", { key: "ArrowLeft" });

        yield* play.expect(button("Week 9")).toExist();

        assert.deepStrictEqual(asked(play.root.emitted), []);
      }),
    );
  });
});

const SwipeMessage = UiSchema.TaggedEnum({ RequestedNextPane: {}, RequestedPreviousPane: {} });

/** A swipeable pane, and every week it was swiped toward. */
const Swipeable = Html.component({
  name: "Swipeable",
  model: Schema.Array(Schema.String),
  message: SwipeMessage,
}).make({
  init: () => [],
  update: {
    RequestedNextPane: ($) => [...$.model, "next"],
    RequestedPreviousPane: ($) => [...$.model, "previous"],
  },
  view: (h) =>
    WeekPane(h, {
      props: { week: 1, swipe: true },
      slots: { content: h.p("week 1") },
      onEmit: {
        RequestedNext: () => SwipeMessage.RequestedNextPane(),
        RequestedPrevious: () => SwipeMessage.RequestedPreviousPane(),
      },
    }),
});

describe("swiping a week's pane", () => {
  it.layer(page(), { buildPerTest: true })("swipes", (it) => {
    const drag = (play: { fire: HtmlPlay.HtmlPlay<ReadonlyArray<string>, never, never>["fire"] }, pointerType: string, dx: number, dy = 0) =>
      Effect.gen(function* () {
        yield* play.fire(pane, "pointerdown", { x: 200, y: 200, pointerType });

        yield* play.fire(pane, "pointerup", { x: 200 + dx, y: 200 + dy, pointerType });
      });

    it.effect("reads a sideways swipe as the next week leftward and the last week rightward", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Swipeable, {});

        yield* drag(play, "touch", -SWIPE_DISTANCE - 10);

        yield* drag(play, "touch", SWIPE_DISTANCE + 10);

        assert.deepStrictEqual(play.root.model(), ["next", "previous"]);
      }),
    );

    it.effect("ignores a mouse drag, a short wobble and a mostly vertical scroll", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Swipeable, {});

        yield* drag(play, "mouse", -200);

        yield* drag(play, "touch", -20);

        yield* drag(play, "touch", -80, 120);

        assert.deepStrictEqual(play.root.model(), []);
      }),
    );
  });
});

const league = (search: { week?: number; day?: string }) =>
  AppRoute.League({ params: { competition: "nba-yahoo", league: "1" }, search });

describe("weekShown", () => {
  it("is the week being played unless the address names another week of the season", () => {
    assert.deepStrictEqual(weekShown(range(10), league({})), { browsing: null, shown: range(10) });

    assert.deepStrictEqual(weekShown(range(10), league({ week: 4 })), { browsing: 4, shown: range(4) });

    assert.deepStrictEqual(weekShown(range(10), league({ week: 10 })).browsing, null);
  });

  it("takes a week outside the season for the week being played", () => {
    assert.deepStrictEqual(weekShown(range(10), league({ week: 40 })), { browsing: null, shown: range(10) });
  });

  it("shows nothing before the season's weeks are known", () => {
    assert.deepStrictEqual(weekShown(undefined, league({ week: 4 })), { browsing: null, shown: undefined });
  });
});

const StepMessage = UiSchema.TaggedEnum({ ClickedStep: { week: Schema.Number } });

/** A page that steps its address to a week, as a panel does from its stepper. */
const Stepping = Html.component({
  name: "Stepping",
  props: Schema.Struct({ route: AppRoute }),
  model: Schema.Null,
  message: StepMessage,
}).make({
  init: () => null,
  update: { ClickedStep: ($, { week }) => $.run(stepWeek($.props.route, range(10), week)) },
  view: (h) =>
    h.div(
      h.button.attr("type", "button").on("click", StepMessage.ClickedStep({ week: 4 })).children("to 4"),
      h.button.attr("type", "button").on("click", StepMessage.ClickedStep({ week: 10 })).children("to 10"),
    ),
});

describe("stepWeek", () => {
  it.layer(page("/nba-yahoo/1?day=2026-11-24"), { buildPerTest: true })("the address", (it) => {
    it.effect("names a week in the address, as a history entry, and drops the day", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Stepping, Router.props(AppRoute));

        yield* play.click("to 4");

        const router = yield* Router.Router;

        assert.strictEqual(router.location().url, "/nba-yahoo/1?week=4");

        assert.strictEqual(router.location().action, "push");
      }),
    );

    it.effect("leaves the week being played off the address", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Stepping, Router.props(AppRoute));

        yield* play.click("to 10");

        const router = yield* Router.Router;

        assert.strictEqual(router.location().url, "/nba-yahoo/1");
      }),
    );
  });
});
