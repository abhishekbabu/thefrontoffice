/**
 * Tooltips, drawn once so no caller assembles the kit's four parts by hand.
 *
 * The kit's tooltip rather than a `title` attribute because a native tooltip
 * is invisible to keyboard focus, cannot be styled, and waits a second before
 * appearing — which for a control whose label lives in the tooltip is a
 * control with no label at all.
 *
 * The kit leaves whether a tooltip is open to whoever draws it, so each
 * control with one keeps `open` in its own Model and passes the requests
 * `Tip` reports back as messages.
 */
import { Tooltip, TooltipProvider } from "@effect/ui-kit";
import type { View } from "@effect/ui";
import type { Html } from "@effect/ui/html";
import { Schema } from "effect";

/** The side of its control a tooltip shows on. */
export const Side = Schema.Literals(["top", "right", "bottom", "left"]);

export type Side = typeof Side.Type;

/** Waited on the first hover; once one tooltip has shown, its neighbours open at once, for this long after. */
const DELAY = 250;
const SKIP_DELAY = 400;

/** The tooltips' shared timing, around everything that has one: hovering along a toolbar opens each at once. */
export function TipGroup<M, C extends View.Children<M>>(h: Html.H<M>, children: C) {
  return TooltipProvider(h, { props: { timeout: SKIP_DELAY }, view: () => h.div.class("contents").children(children) });
}

/** The kit's parts as `Tip` hands them to the trigger it draws. */
type Parts<M> = Parameters<NonNullable<Parameters<typeof Tooltip<M>>[1]["view"]>>[0];

/**
 * A tooltip of `label` on the control `trigger` draws, open while `open`.
 *
 * `trigger` is given the kit's parts and returns the control with
 * `tooltip.trigger` applied: a `<button>` or a link. `key` tells two tooltips
 * of one component apart, as the kit's own instance needs.
 */
export function Tip<M>(
  h: Html.H<M>,
  options: {
    key: string;
    open: boolean;
    label: string;
    side?: Side | undefined;
    onOpen: M;
    onClose: M;
    trigger: (tooltip: Parts<M>) => View.Content<M>;
  },
) {
  return Tooltip(h, {
    key: options.key,
    props: { open: options.open && options.label !== "", delay: DELAY, side: options.side ?? "bottom", sideOffset: 6 },
    onEmit: { RequestedOpen: () => options.onOpen, RequestedClose: () => options.onClose },
    // `contents`: the wrapper takes no box, so the control sits in its parent's layout as if alone.
    view: (tooltip) =>
      h.span.class("contents").children(
      options.trigger(tooltip),
      tooltip
        .positioner(h.div.class("z-50 m-0 overflow-visible border-0 bg-transparent p-0"))
        .children(
          tooltip
            .popup(
              h.div.class(
                // Grows out of the control it names, from the side it was placed
                // on. Not when it follows the pointer from a neighbouring control
                // (`data-instant`): sweeping along a toolbar should not pulse.
                "relative max-w-xs origin-(--transform-origin) animate-[tooltip-in_120ms_cubic-bezier(0.22,1,0.36,1)] rounded-md border border-border bg-popover px-2.5 py-1.5 text-[12.5px] leading-snug text-popover-foreground shadow-md data-[instant=delay]:animate-none motion-reduce:animate-none",
              ),
            )
            .children(
              options.label,
              tooltip.arrow(
                h.div.class(
                  "-z-10 size-2.5 rotate-45 border-border bg-popover data-[side=bottom]:-top-[5px] data-[side=bottom]:border-t data-[side=bottom]:border-l data-[side=top]:-bottom-[5px] data-[side=top]:border-r data-[side=top]:border-b data-[side=left]:-right-[5px] data-[side=left]:border-t data-[side=left]:border-r data-[side=right]:-left-[5px] data-[side=right]:border-b data-[side=right]:border-l",
                ),
              ),
            ),
        ),
      ),
  });
}
