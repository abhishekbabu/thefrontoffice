import type { Html } from "@effect/ui/html";
import { pressable } from "@/lib/motion/press";
import { cn } from "@/lib/utils";

/**
 * The name the browser morphs a choice's marker under, from the option it
 * left to the one picked (`::view-transition-group` in index.css). The update
 * that changes the choice asks for the morph with
 * `$.viewTransition([MARKER])`; one marker per `group` shows at a time, so
 * two rows on a page never trade theirs.
 */
export const MARKER = "marker";

export const markerName = (group: string) => `${MARKER}-${group}`;

/**
 * A row of tabs: which part of a page is shown.
 *
 * Quieter than a `ToggleChip`, which filters what a list holds; a tab changes
 * what the page shows. The chosen tab's ground slides to the next one picked,
 * so the eye follows the choice rather than finding it again.
 */
export function Tabs<M, T extends string>(
  h: Html.H<M>,
  {
    group,
    tabs,
    current,
    onPick,
    class: extra,
  }: {
    /** Which row of tabs this is, unique on the page. */
    group: string;
    tabs: { id: T; label: string }[];
    current: T | undefined;
    onPick: (id: T) => M;
    class?: string | undefined;
  },
) {
  return h.div.attrs({ class: cn("flex items-center gap-1 overflow-x-auto", extra), role: "tablist" }).children(
    tabs.map((t) =>
      h.button
        .key(t.id)
        .attrs({
          type: "button",
          role: "tab",
          "aria-selected": String(t.id === current),
          class: cn(
            "relative isolate shrink-0 rounded-md px-3 py-1.5 text-[13px] font-medium",
            pressable,
            t.id === current ? "text-foreground" : "text-muted-foreground hover:bg-muted",
          ),
        })
        .on("click", onPick(t.id))
        .on("keydown", () => undefined)
        .children(
          t.id === current &&
            h.span
              .attrs({ "aria-hidden": "true", class: "absolute inset-0 -z-10 rounded-md bg-secondary [view-transition-class:marker]" })
              .style({ viewTransitionName: markerName(group) }),
          t.label,
        ),
    ),
  );
}
