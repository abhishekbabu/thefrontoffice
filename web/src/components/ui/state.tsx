import { m } from "motion/react";
import { Skeleton } from "@/components/ui/skeleton";
import { fade, rise } from "@/lib/motion";
import { cn } from "@/lib/utils";

/**
 * The three things every panel does while it has nothing to show.
 *
 * They were hand-rolled per panel and drifted: one showed a spinner, one three
 * skeleton bars, one nothing at all, and each described an empty result in its
 * own words. Waiting should look the same everywhere, because it means the
 * same thing everywhere.
 */

/** A placeholder shaped like the thing that is coming. */
export function Loading({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <m.div
      variants={fade}
      initial="hidden"
      animate="shown"
      className={cn("flex flex-col gap-3 p-5", className)}
      // Announced politely: a screen reader should hear that something is
      // coming, not have the page read out again as rows arrive.
      role="status"
      aria-live="polite"
      aria-label="Loading"
    >
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn("h-12 w-full", i === 0 && "h-8 w-64")} />
      ))}
    </m.div>
  );
}

/** Nothing to show, said once and in the same shape every time. */
export function Empty({ title, detail, action }: { title: string; detail?: string; action?: React.ReactNode }) {
  return (
    <m.div
      variants={rise}
      initial="hidden"
      animate="shown"
      className="flex flex-col items-start gap-3 px-5 py-10 text-left"
    >
      <p className="font-display text-[17px] font-semibold tracking-tight">{title}</p>
      {detail && <p className="max-w-[60ch] text-[13.5px] leading-relaxed text-muted-foreground">{detail}</p>}
      {action}
    </m.div>
  );
}

/**
 * A line of text inside a card where its rows would be: "Nothing to do", "No leagues this season".
 *
 * `Empty` is for a page with nothing on it; this is for one card of a page
 * that has nothing, where a headline-sized message would shout.
 */
export function CardNote({ children }: { children: React.ReactNode }) {
  return <p className="px-4 py-3 text-[13px] text-muted-foreground">{children}</p>;
}

/**
 * Work under way, said in a card header's corner: "judging…", "Thinking…".
 *
 * In the header's own type, but in sentence case: it is a status, not a label.
 */
export function Busy({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-normal normal-case tracking-normal" role="status">
      {children}
    </span>
  );
}
