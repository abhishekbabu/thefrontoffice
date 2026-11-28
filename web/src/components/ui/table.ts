import type { Html } from "@effect/ui/html";
import { cn } from "@/lib/utils";
import { LABEL } from "@/components/ui/label";

/** Wide tables scroll inside themselves; the page never scrolls sideways. */
export function Table<M>(h: Html.H<M>, extra?: string) {
  return h.table
    .attr("class", cn("w-full border-collapse text-[13px]", extra))
    .forward((table) => h.div.class("w-full overflow-x-auto").children(table));
}

export function Th<M>(h: Html.H<M>, extra?: string) {
  return h.th.attr("class", cn("whitespace-nowrap border-b border-border px-4 py-2 text-left", LABEL, extra));
}

export function Td<M>(h: Html.H<M>, extra?: string) {
  return h.td.attr("class", cn("border-b border-border/45 px-4 py-2 tabular-nums", extra));
}
