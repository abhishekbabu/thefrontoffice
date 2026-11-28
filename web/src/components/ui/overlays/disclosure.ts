import type { View } from "@effect/ui";
import type { Html } from "@effect/ui/html";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

/**
 * Something kept out of the way under a labelled row that opens it: the to-do
 * items put aside, the steps for reading Yahoo without its API.
 *
 * A native `<details>`, so it opens by keyboard and is found by the browser's
 * own search with nothing to wire. Its summary is a label, ruled off from
 * whatever sits above it in the card. Open on arrival where `open` says so,
 * and the reader's own after that.
 */
export function Disclosure<M, S extends View.Children<M>, C extends View.Children<M>>(
  h: Html.H<M>,
  { summary, open = false, class: extra, children }: { summary: S; open?: boolean; class?: string | undefined; children: C },
) {
  return h.details
    .attrs({ class: cn("border-t border-border", extra), open: open ? "" : undefined })
    .children(Label(h, { as: "summary", class: "cursor-pointer px-4 py-2.5 hover:text-foreground" }).children(summary), children);
}
