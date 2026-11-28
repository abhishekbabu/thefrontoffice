import { Command, Router, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Schema } from "effect";
import { arrowKeys } from "@/components/league/week-stepper";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/controls/button";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Icon } from "@/components/ui/icon";
import { addDays, dayLabel, isDay } from "@/lib/days";
import type { AppRoute } from "@/lib/route";
import type { Summary } from "@/lib/types";
import { wire } from "@/lib/wire";

/** Which day of a week a day's summary shows, and the week's days to page through. */
export type DayRange = NonNullable<Summary["days"]>;

const DayStepperMessage = UiSchema.TaggedEnum({
  ClickedDay: { day: Schema.String },
  PressedArrowKey: { day: Schema.String },
});

/** `RequestedDay`: the day asked for, by an arrow, a key or the way back to today. The page steps its address to it. */
const DayStepperEvents = UiSchema.TaggedEnum({ RequestedDay: { day: Schema.String } });

/**
 * Paging through a week a day at a time, where a lineup is set day by day: a
 * step either way inside the week, and the way back to today while the week
 * holds it. The arrow keys do the same. Each control names the day it goes to.
 */
export const DayStepper = Html.component({
  name: "DayStepper",
  props: Schema.Struct({ range: wire<DayRange>() }),
  model: Schema.Null,
  message: DayStepperMessage,
  events: DayStepperEvents,
}).make({
  init: () => null,
  update: {
    ClickedDay: ($, { day }) => $.emit(DayStepperEvents.RequestedDay({ day })),
    PressedArrowKey: ($, { day }) => $.emit(DayStepperEvents.RequestedDay({ day })),
  },
  view: (h) => {
    const { day, first, last, today } = h.props.range;
    const before = addDays(day, -1);
    const after = addDays(day, 1);

    return h.div.attrs({ class: "flex items-center gap-1", role: "group", "aria-label": "Day" }).children(
      IconButton(h, {
        key: "earlier",
        props: { label: dayLabel(before), icon: "chevron-left", disabled: day <= first },
        onEmit: { Clicked: () => DayStepperMessage.ClickedDay({ day: before }) },
      }),
      // Fixed width, as the week's: the arrows stay put whichever day is shown.
      h.div.class("flex w-28 flex-col items-center gap-0.5").children(
        h.span.attrs({ class: "font-mono text-[12px] tabular-nums", "aria-live": "polite" }).children(dayLabel(day)),
        today === day
          ? Badge(h, { variant: "muted", appearance: "label", class: "h-4 px-1.5 text-[10.5px]" }).children("today")
          : today
            ? Button(h, { variant: "ghost", class: "h-4 gap-1 px-1.5 font-mono text-[10.5px] text-muted-foreground" })
                .attr("aria-label", `Back to today (${dayLabel(today)})`)
                .on("click", DayStepperMessage.ClickedDay({ day: today }))
                .children(Icon(h, "undo-2", { class: "size-2.5" }), "today")
            : // A week without today has no way back to it: the line stays, so the label does not jump.
              h.span.attrs({ "aria-hidden": "true", class: "h-4" }),
      ),
      IconButton(h, {
        key: "later",
        props: { label: dayLabel(after), icon: "chevron-right", disabled: day >= last },
        onEmit: { Clicked: () => DayStepperMessage.ClickedDay({ day: after }) },
      }),
    );
  },
  subscriptions: ({ props }) => {
    const { day, first, last } = props.range;

    return [
      arrowKeys(
        day > first ? DayStepperMessage.PressedArrowKey({ day: addDays(day, -1) }) : undefined,
        day < last ? DayStepperMessage.PressedArrowKey({ day: addDays(day, 1) }) : undefined,
      ),
    ];
  },
});

/**
 * Which day of the shown week a page opens, named in its address as
 * `?day=2026-11-24` beside `?week=`: null where the address names none, or
 * names something that is not a day.
 */
export function dayAsked(route: AppRoute): string | null {
  // Only a league's pages carry a search; the others name no day.
  const asked =
    route._tag === "Competition" || route._tag === "League" || route._tag === "View" ? (route.search.day ?? null) : null;

  return isDay(asked) ? asked : null;
}

/**
 * Steps the address to day `to` of the week `range` steps within, keeping the
 * week, with a history entry per step.
 *
 * Left off for the day a week opens on — today in the week being played,
 * else its first — so that address stays the week's own. Stepping the week
 * (`stepWeek`) drops the day, and the next week opens on its own. Built on
 * `PatchSearch` for the reason `stepWeek` is.
 */
export function stepDay(route: AppRoute, range: DayRange, to: string) {
  return Router.PatchSearch.make({
    route,
    patch: { day: to === (range.today ?? range.first) ? undefined : to },
    history: "push",
    scroll: false,
  }).pipe(Command.asNoop);
}
