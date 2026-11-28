import { Command, Router, Subscription, UiSchema } from "@effect/ui";
import { Html, HtmlSubscription } from "@effect/ui/html";
import { Schema, Stream } from "effect";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/controls/button";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Icon } from "@/components/ui/icon";
import type { AppRoute } from "@/lib/route";
import type { WeekRange } from "@/lib/types";
import { cn } from "@/lib/utils";
import { wire } from "@/lib/wire";

/**
 * The arrow keys stepping a page, unless something is being typed into, which
 * an arrow key must stay with, or a modifier makes the press somebody else's.
 * A step with nowhere to go (`undefined`) leaves the key alone. Not cancelled:
 * an arrow key nobody steps with still scrolls.
 */
export function arrowKeys<M>(onLeft: M | undefined, onRight: M | undefined) {
  return HtmlSubscription.onDocument("keydown", ({ key, alt, ctrl, meta, shift, editable }) => {
    if (alt || ctrl || meta || shift || editable) return undefined;

    if (key === "ArrowLeft") return onLeft;

    if (key === "ArrowRight") return onRight;

    return undefined;
  });
}

const capitalized = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

const WeekStepperMessage = UiSchema.TaggedEnum({
  ClickedWeek: { week: Schema.Number },
  PressedArrowKey: { week: Schema.Number },
});

/** `RequestedWeek`: the week asked for, by an arrow, a key or the way back. The page steps its address to it. */
const WeekStepperEvents = UiSchema.TaggedEnum({ RequestedWeek: { week: Schema.Number } });

/**
 * Paging through the season a week at a time: a step either way, and the way back to the week being played.
 *
 * The arrow keys do the same, as does a sideways swipe on a `WeekPane` with
 * `swipe` on. Each control says which week it goes to, because "next" alone
 * does not say whether next is the week you want.
 *
 * `word` is what the competition calls a round — FPL's are gameweeks — and is
 * said in every label here, so the stepper agrees with the page under it.
 * `keys` off where a finer stepper beside it — a week's days — has the arrows.
 */
export const WeekStepper = Html.component({
  name: "WeekStepper",
  props: Schema.Struct({
    range: wire<WeekRange>(),
    word: Schema.optional(Schema.String),
    keys: Schema.optional(Schema.Boolean),
  }),
  model: Schema.Null,
  message: WeekStepperMessage,
  events: WeekStepperEvents,
}).make({
  init: () => null,
  update: {
    ClickedWeek: ($, { week }) => $.emit(WeekStepperEvents.RequestedWeek({ week })),
    PressedArrowKey: ($, { week }) => $.emit(WeekStepperEvents.RequestedWeek({ week })),
  },
  view: (h) => {
    const word = h.props.word ?? "week";
    const Word = capitalized(word);
    const { week, current, first, last } = h.props.range;

    return h.div.attrs({ class: "flex items-center gap-1", role: "group", "aria-label": Word }).children(
      IconButton(h, {
        key: "earlier",
        props: { label: `${Word} ${week - 1}`, icon: "chevron-left", disabled: week <= first },
        onEmit: { Clicked: () => WeekStepperMessage.ClickedWeek({ week: week - 1 }) },
      }),
      // The week and where it stands, stacked in a column of fixed width, so
      // the arrows stay put whichever week is shown and whatever is said under it.
      h.div.class("flex w-28 flex-col items-center gap-0.5").children(
        h.span.attrs({ class: "font-mono text-[12px] tabular-nums", "aria-live": "polite" }).children(`${Word} ${week}`),
        // Said, not only implied by the controls: which week this is relative to now.
        week === current
          ? Badge(h, { variant: "muted", appearance: "label", class: "h-4 px-1.5 text-[10.5px]" }).children(`this ${word}`)
          : Button(h, { variant: "ghost", class: "h-4 gap-1 px-1.5 font-mono text-[10.5px] text-muted-foreground" })
              .attr("aria-label", `Back to this ${word} (${word} ${current})`)
              .on("click", WeekStepperMessage.ClickedWeek({ week: current }))
              .children(Icon(h, "undo-2", { class: "size-2.5" }), `${word} ${current}`),
      ),
      IconButton(h, {
        key: "later",
        props: { label: `${Word} ${week + 1}`, icon: "chevron-right", disabled: week >= last },
        onEmit: { Clicked: () => WeekStepperMessage.ClickedWeek({ week: week + 1 }) },
      }),
    );
  },
  subscriptions: ({ props }) => {
    const { week, first, last } = props.range;

    return [
      props.keys !== false &&
        arrowKeys(
          week > first ? WeekStepperMessage.PressedArrowKey({ week: week - 1 }) : undefined,
          week < last ? WeekStepperMessage.PressedArrowKey({ week: week + 1 }) : undefined,
        ),
    ];
  },
});

/** How far a finger has to travel sideways, in pixels, before it is a swipe rather than a wobble. */
export const SWIPE_DISTANCE = 60;

type Point = { x: number; y: number };

/** Which way a touch from `from` to `to` swiped: leftward for the next, rightward for the last, or neither. */
function swiped(from: Point, to: Point): "next" | "previous" | null {
  const dx = to.x - from.x;
  const dy = to.y - from.y;

  // Mostly sideways only: a diagonal flick is somebody scrolling.
  if (Math.abs(dx) < SWIPE_DISTANCE || Math.abs(dx) < 2 * Math.abs(dy)) return null;

  return dx < 0 ? "next" : "previous";
}

const WeekPaneMessage = UiSchema.TaggedEnum({
  /** The week asked for is the one on screen now: it was not pending, or no longer is. */
  ArrivedWeek: { week: Schema.Number },
  PressedPane: { x: Schema.Number, y: Schema.Number, touch: Schema.Boolean },
  ReleasedPane: { x: Schema.Number, y: Schema.Number },
});

/** A sideways swipe on the pane: left for the next week, right for the last. The page steps to it. */
const WeekPaneEvents = UiSchema.TaggedEnum({ RequestedNext: {}, RequestedPrevious: {} });

/**
 * A week's content, coming in from the side it was stepped toward: the next
 * week from the right, the last from the left, the way the arrows point.
 *
 * `pending` while the week asked for is still loading and the last one is
 * held on screen (a query's `waiting`): the content changes when the new
 * week's arrives, not before, so it moves once. Where there is no direction —
 * the first week shown — it only fades in, over the placeholder it replaces.
 * The week on screen is said as `data-week`.
 *
 * The week it holds is kept in the Model, and the view reads a new week
 * against it in the same render it arrives in, so the pane is replaced, in
 * from the right side, in that frame; the Model catches up a moment later
 * with the same answer, so nothing moves twice.
 *
 * With `swipe`, a sideways swipe asks for the next or the last week. Touch
 * only: a mouse drag is selecting text.
 */
export const WeekPane = Html.component({
  name: "WeekPane",
  props: Schema.Struct({
    week: Schema.Number,
    pending: Schema.optional(Schema.Boolean),
    swipe: Schema.optional(Schema.Boolean),
    class: Schema.optional(Schema.String),
  }),
  model: Schema.Struct({
    shown: Schema.Number,
    direction: Schema.Number,
    start: Schema.NullOr(Schema.Struct({ x: Schema.Number, y: Schema.Number })),
  }),
  message: WeekPaneMessage,
  events: WeekPaneEvents,
  slots: ["content"],
  restore: false,
}).make({
  init: ($) => ({ shown: $.props.week, direction: 0, start: null }),
  update: {
    ArrivedWeek: ($, { week }) => $.evolve({ shown: week, direction: Math.sign(week - $.model.shown) }),
    PressedPane: ($, { x, y, touch }) => $.evolve({ start: touch ? { x, y } : null }),
    ReleasedPane: ($, to) => {
      const from = $.model.start;
      const step = $.evolve({ start: null });

      if (from === null) return step;

      const way = swiped(from, to);

      if (way === null) return step;

      return step.emit(way === "next" ? WeekPaneEvents.RequestedNext() : WeekPaneEvents.RequestedPrevious());
    },
  },
  view: (h, model) => {
    const arriving = h.props.pending !== true && h.props.week !== model.shown;
    const shown = arriving ? h.props.week : model.shown;
    const direction = arriving ? Math.sign(h.props.week - model.shown) : model.direction;

    const pane = h.div.key(String(shown)).attrs({
      "data-week": String(shown),
      class: cn(
        direction > 0 && "animate-step-next",
        direction < 0 && "animate-step-back",
        direction === 0 && "animate-fade",
        h.props.class,
      ),
    });

    const swiping =
      h.props.swipe === true
        ? pane
            .on("pointerdown", ({ x, y, pointerType }) =>
              WeekPaneMessage.PressedPane({ x, y, touch: pointerType === "touch" }),
            )
            .on("pointerup", ({ x, y }) => WeekPaneMessage.ReleasedPane({ x, y }))
        : pane;

    return swiping.children(h.slots.content);
  },
  subscriptions: ({ model, props }) => [
    props.pending !== true &&
      props.week !== model.shown &&
      Subscription.make("arrived", props.week, (week) => Stream.make(WeekPaneMessage.ArrivedWeek({ week }))),
  ],
});

/** The week asked for, if it is not the one being played, and the range at the week shown. */
type WeekShown = { browsing: number | null; shown: WeekRange | undefined };

/**
 * Which week a page shows, named in its address as `?week=7`, against the season's `range`.
 *
 * `browsing` is the week asked for when it is not the week being played,
 * else null; `shown` is the range at the week shown. The week being played
 * leaves the parameter off, so its address is the page's own. A week outside
 * the season is the week being played: an address somebody trimmed is not an
 * error worth a page.
 */
export function weekShown(
  range: WeekRange | undefined,
  route: AppRoute,
): WeekShown {
  if (range === undefined) return { browsing: null, shown: undefined };

  // Only a league's pages carry a search; the others name no week.
  const asked =
    route._tag === "Competition" || route._tag === "League" || route._tag === "View" ? (route.search.week ?? null) : null;

  const browsing =
    asked !== null && asked !== range.current && asked >= range.first && asked <= range.last ? asked : null;

  return { browsing, shown: { ...range, week: browsing ?? range.current } };
}

/**
 * Steps the address to week `to`: a history entry per step, so Back returns
 * through the weeks visited. The week being played clears the parameter, and
 * any step drops the day, so the next week opens on its own.
 *
 * Built on the Router's `PatchSearch` rather than `Router.patchSearch`, which
 * types its patch by a route known to carry a search: a page holds the whole
 * `AppRoute`, and every page that steps is one that does.
 */
export function stepWeek(route: AppRoute, range: WeekRange, to: number) {
  return Router.PatchSearch.make({
    route,
    patch: { week: to === range.current ? undefined : to, day: undefined },
    history: "push",
    scroll: false,
  }).pipe(Command.asNoop);
}
