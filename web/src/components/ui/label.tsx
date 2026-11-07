import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * The small mono uppercase label: a section's name, a row's key, a column's head.
 *
 * Mono uppercase at a small size reads as chrome rather than content, which
 * keeps it from competing with the data beside it. One size and one tracking
 * everywhere: written inline, it drifted to four of each.
 */
export const LABEL = "font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground";

type Tag = "span" | "div" | "p" | "h3" | "summary";

/** `children` as a label, in whichever element the place calls for: an `h3` heading a section, a `span` in a row. */
export function Label({
  as: Element = "span",
  className,
  children,
}: {
  as?: Tag;
  className?: string;
  children: React.ReactNode;
}) {
  return <Element className={cn(LABEL, className)}>{children}</Element>;
}
