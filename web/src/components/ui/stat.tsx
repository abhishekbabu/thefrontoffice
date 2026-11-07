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
    <div className="flex flex-wrap border-b border-border">
      {stats.map((stat) => (
        <div
          key={stat.label}
          // Not on the last: a divider with nothing after it reads as an empty
          // cell stretching to the edge.
          className="min-w-[7rem] border-border px-5 py-2.5 [&:not(:last-child)]:border-r"
        >
          <Label>{stat.label}</Label>
          <div
            className={cn(
              "mt-0.5 font-display text-[19px] font-semibold tracking-tight tabular-nums",
              toneText(stat.tone),
            )}
          >
            {stat.value}
          </div>
        </div>
      ))}
    </div>
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
          <dd className={cn("text-right font-mono text-[13px] tabular-nums", toneText(stat.tone))}>{stat.value}</dd>
        </div>
      ))}
    </dl>
  );
}
