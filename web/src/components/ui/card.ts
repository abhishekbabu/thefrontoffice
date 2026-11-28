import type { Html } from "@effect/ui/html";
import { cn } from "@/lib/utils";

/** A card: the ground every panel's sections sit on. */
export function Card<M>(h: Html.H<M>, extra?: string) {
  return h.div.attr("class", cn("rounded-lg border border-border bg-card text-card-foreground", extra));
}

/** The label row every panel shares. Mono uppercase at a small size reads as
 *  chrome rather than content, which keeps it from competing with the data. */
export function CardHeader<M>(h: Html.H<M>, extra?: string) {
  return h.div.attr(
    "class",
    cn(
      "flex items-center justify-between gap-3 border-b border-border px-4 py-2.5",
      "font-mono text-[12px] font-semibold uppercase tracking-[0.04em] text-muted-foreground",
      extra,
    ),
  );
}
