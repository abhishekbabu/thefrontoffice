/**
 * The three things every panel does while it has nothing to show.
 *
 * They were hand-rolled per panel and drifted: one showed a spinner, one three
 * skeleton bars, one nothing at all, and each described an empty result in its
 * own words. Waiting should look the same everywhere, because it means the
 * same thing everywhere.
 */
import type { View } from "@effect/ui";
import type { Html } from "@effect/ui/html";
import { Cause } from "effect";
import { AsyncResult } from "effect/reactivity";
import { ErrorNote } from "@/components/ui/error-note";
import { LoadingBar } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

/**
 * Something is on its way: a loading bar at the top of where it will land.
 *
 * `lines` is roughly how many rows are coming, and holds that much room open
 * so the page does not jump when they arrive.
 */
export function Loading<M>(h: Html.H<M>, { lines = 3, class: extra }: { lines?: number; class?: string } = {}) {
  return h.div
    .attrs({
      class: cn("animate-fade p-5", extra),
      // Announced politely: a screen reader should hear that something is
      // coming, not have the page read out again as rows arrive.
      role: "status",
      "aria-live": "polite",
    })
    .style({ minHeight: `${lines * 3.75 + 2.5}rem` })
    .children(LoadingBar(h));
}

/**
 * What a query shows before it has an answer: a loading bar while it is
 * asked, the failure if it fails, and nothing once the data is in — the caller
 * renders that.
 */
export function QueryState<M, A, E>(
  h: Html.H<M>,
  result: AsyncResult.AsyncResult<A, E>,
  { lines, class: extra }: { lines?: number; class?: string } = {},
) {
  if (AsyncResult.isInitial(result)) return Loading(h, lines === undefined ? {} : { lines });

  if (AsyncResult.isFailure(result)) return ErrorNote(h, { error: Cause.squash(result.cause), class: extra });

  return null;
}

/** Nothing to show, said once and in the same shape every time. */
export function Empty<M, C extends View.Children<M> = []>(
  h: Html.H<M>,
  { title, detail, action }: { title: string; detail?: string | undefined; action?: C },
) {
  return h.div
    .class("flex animate-rise flex-col items-start gap-3 px-5 py-10 text-left")
    .children(
      h.p.class("font-display text-[17px] font-semibold tracking-tight").children(title),
      detail && h.p.class("max-w-[60ch] text-[13.5px] leading-relaxed text-muted-foreground").children(detail),
      action,
    );
}

/**
 * A line of text inside a card where its rows would be: "Nothing to do", "No leagues this season".
 *
 * `Empty` is for a page with nothing on it; this is for one card of a page
 * that has nothing, where a headline-sized message would shout.
 */
export function CardNote<M>(h: Html.H<M>) {
  return h.p.class("px-4 py-3 text-[13px] text-muted-foreground");
}

/**
 * Work under way, said in a card header's corner: "judging…", "Thinking…".
 *
 * In the header's own type, but in sentence case: it is a status, not a label.
 */
export function Busy<M>(h: Html.H<M>) {
  return h.span.attrs({ class: "font-normal normal-case tracking-normal", role: "status" });
}
