import type { Html } from "@effect/ui/html";
import { Icon } from "@/components/ui/icon";
import { cn } from "@/lib/utils";

const FIELD =
  "h-9 w-full min-w-0 rounded-md border border-input bg-background px-3 text-[13px] placeholder:text-muted-foreground focus-visible:border-ring disabled:opacity-50";

/**
 * A single-line text field: the chat box, the wire's search, a setting.
 *
 * Each was styled where it stood and they drifted — two borders, two heights,
 * and one that switched off the focus ring every other control keeps. The
 * ring comes from the global `:focus-visible` rule, so nothing here removes it.
 */
export function Input<M>(h: Html.H<M>, extra?: string) {
  return h.input.attr("class", cn(FIELD, extra));
}

/**
 * A text field with a magnifier in it: the wire's search, the compare finder.
 *
 * Written twice with the icon placed by hand, and the two placements differed
 * by the padding of whatever each sat in. Placed against the field here, so it
 * lands in the same spot wherever the field goes. The field is the builder
 * returned, so the caller's value, name and handlers land on it.
 */
export function SearchInput<M>(h: Html.H<M>, extra?: string) {
  return Input(h, "pl-8").forward((field) =>
    h.div
      .attr("class", cn("relative min-w-0", extra))
      .children(
        Icon(h, "search", {
          class: "pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground",
        }),
        field,
      ),
  );
}
