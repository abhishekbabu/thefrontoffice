import type { Html } from "@effect/ui/html";
import { markerName } from "@/components/ui/controls/tabs";
import { pressable } from "@/lib/motion/press";
import { cn } from "@/lib/utils";

/**
 * One choice of several, pressed or not: a position filter, a team, a palette.
 *
 * Three groups had three looks for "this one is chosen" — a fill, an outline,
 * a tint — which read as three kinds of control. One fill now, because it is
 * the one that holds up for a reader who cannot see the hue: the chosen chip
 * changes its ground and its text, not only its colour. Tabs are not this:
 * they change what the page shows, and stay quieter.
 *
 * Chips of one `group`, of which exactly one is chosen — a team, a palette, a
 * setting's value — slide their fill from the old choice to the new rather
 * than blinking out on one and in on the other, when the update that changes
 * the choice asks for it (`MARKER` in `controls/tabs.ts`).
 *
 * The border is kept, transparent, on the chosen chip: without it a chip is
 * two pixels narrower pressed than not, and the row shifts under the click.
 */
export function ToggleChip<M>(
  h: Html.H<M>,
  { pressed, onClick, group, class: extra }: { pressed: boolean; onClick: M; group?: string | undefined; class?: string | undefined },
) {
  return h.button
    .attrs({
      type: "button",
      "aria-pressed": String(pressed),
      class: cn(
        "relative isolate flex h-9 items-center gap-2 rounded-md border px-3 text-[13px]",
        pressable,
        pressed ? "border-transparent text-primary-foreground" : "border-border hover:bg-muted",
        pressed && group === undefined && "bg-primary",
        extra,
      ),
    })
    .on("click", onClick)
    .on("keydown", () => undefined)
    .children(
      pressed &&
        group !== undefined &&
        h.span
          .attrs({ "aria-hidden": "true", class: "absolute -inset-px -z-10 rounded-md bg-primary [view-transition-class:marker]" })
          .style({ viewTransitionName: markerName(group) }),
    );
}
