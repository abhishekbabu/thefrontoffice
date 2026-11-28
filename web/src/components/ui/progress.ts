import type { Html } from "@effect/ui/html";
import { cn } from "@/lib/utils";

/**
 * A slim bar with a segment sweeping across it: work under way, of a length
 * nobody knows.
 *
 * Indeterminate on purpose. The server says nothing about how far along a
 * league's first load is, so a bar that filled would be inventing a figure;
 * a sweep says only that something is moving, which is true. It replaced
 * shimmering placeholder rows, which at a glance read as a page that had
 * loaded empty rather than one still on its way.
 *
 * The sweep is CSS (`animate-loading-bar` in index.css). A viewer who asked
 * for stillness gets the segment held in place, and the word beside it
 * carries the state either way.
 */
export function LoadingBar<M>(h: Html.H<M>, { label = "Loading", class: extra }: { label?: string; class?: string } = {}) {
  return h.div.attr("class", cn("flex flex-col gap-2", extra)).children(
    h.div
      .attrs({
        role: "progressbar",
        "aria-label": label,
        class: "relative h-1 w-full overflow-hidden rounded-full bg-secondary",
      })
      .children(
        h.div.class(
          "absolute inset-y-0 left-0 w-2/5 rounded-full bg-primary motion-safe:animate-loading-bar motion-reduce:left-[30%]",
        ),
      ),
    h.span.class("font-mono text-[11px] tracking-wide text-muted-foreground uppercase").children(`${label}…`),
  );
}
