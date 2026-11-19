import type * as React from "react";
import { AnimatePresence, m } from "motion/react";
import { fade } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { toneText } from "@/lib/tone";
import type { Stat } from "@/lib/api";
import { Label } from "@/components/ui/label";

/**
 * Figures as the server sends them — a label, a value already written, and
 * whether it should pull the eye — in the three shapes a page lays them out.
 *
 * Every figure is computed by the provider from live league state, never
 * written by the model, so these can be read as fact.
 */

/** The strip under a page title: where the team stands, before any reading. */
export function StatStrip({ stats }: { stats: Stat[] }) {
  if (!stats.length) return null;
  return (
    // A band under the header, so it spans the column like the header does,
    // its rule reaching the edge while the figures keep to the page's width.
    <div data-bleed className="border-b border-border">
      {/* Each figure's divider is on its left, and the row is pulled a pixel
          left under a clip: whichever figure starts a line — the first, or
          the first after a wrap on a phone — has its divider cut off, and no
          line ends on a divider with nothing after it. */}
      <div className="mx-auto max-w-(--page-max) overflow-hidden">
        <div className="-ml-px flex flex-wrap">
          {stats.map((stat) => (
            <div key={stat.label} className="min-w-[7rem] border-l border-border px-5 py-2.5">
              <Label>{stat.label}</Label>
              <div
                className={cn(
                  "relative mt-0.5 font-display text-[19px] font-semibold tracking-tight tabular-nums",
                  toneText(stat.tone),
                )}
              >
                <Changing value={stat.value} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * A figure that crossfades when it changes — a week stepped, a score
 * updated — rather than being swapped in a frame, and without rolling digits:
 * the new value is to be read, not watched arriving. The old one is lifted out
 * of the flow as it fades (`popLayout`), so the two never stack. Still on
 * arrival: the page's own entrance covers that.
 */
function Changing({ value }: { value: string }) {
  return (
    <AnimatePresence initial={false} mode="popLayout">
      <m.span key={value} variants={fade} initial="hidden" animate="shown" exit="gone" className="inline-block">
        {value}
      </m.span>
    </AnimatePresence>
  );
}

/**
 * Parallel answers to one question, on a grid: reading down a column beats
 * hunting along a strip when there are several of the same kind.
 */
export function StatGrid({ stats }: { stats: Stat[] }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 px-4 py-1 sm:grid-cols-4">
      {stats.map((stat) => (
        <div key={stat.label} className="flex flex-col gap-0.5 py-2.5">
          <Label className="truncate">{stat.label}</Label>
          <span
            className={cn(
              "truncate text-[13px]",
              stat.tone === "good" && "font-medium",
              toneText(stat.tone, "text-muted-foreground"),
            )}
          >
            {stat.value}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Figures as label-and-value lines, read down: a player's season, a week's warnings. */
export function StatList({ stats, className }: { stats: Stat[]; className?: string }) {
  return (
    <dl className={className}>
      {stats.map((stat) => (
        <div
          key={stat.label}
          className="flex items-baseline justify-between gap-3 border-b border-border/45 py-1.5 last:border-b-0"
        >
          <dt className="text-[13px] text-muted-foreground">{stat.label}</dt>
          <dd className={cn("text-right font-mono text-[13px] tabular-nums", toneText(stat.tone))}>
            <Linked url={stat.url}>{stat.value}</Linked>
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** `children`, linked to `url` in a new tab where there is one: a headline opens its article. */
export function Linked({ url, children }: { url?: string; children: React.ReactNode }) {
  if (!url) return <>{children}</>;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => e.stopPropagation()}
      className="underline decoration-border underline-offset-2 hover:text-foreground hover:decoration-foreground"
    >
      {children}
    </a>
  );
}
