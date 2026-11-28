import type { Html } from "@effect/ui/html";
import { cn } from "@/lib/utils";

export function Skeleton<M>(h: Html.H<M>, extra?: string) {
  return h.div.attr("class", cn("animate-pulse rounded-sm bg-muted motion-reduce:animate-none", extra));
}
