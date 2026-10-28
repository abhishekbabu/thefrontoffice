import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * The model's word on one thing on screen — a to-do item, a free agent — under the thing it is about.
 *
 * A stale one stays, faded and labelled beside its badge: the reasoning may
 * still hold, but it was about something that has changed since. The label
 * sits with the badge rather than at the row's far edge, where on a wide
 * screen it ended up a long way from what it qualifies.
 */
export function Verdict({
  label,
  variant,
  reason,
  stale = false,
}: {
  label: string;
  variant: "ok" | "info" | "warn" | "fail" | "muted";
  reason: string;
  stale?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex max-w-[90ch] flex-wrap items-baseline gap-x-2 gap-y-1 rounded-md bg-muted px-2.5 py-1.5 text-[12.5px] leading-relaxed",
        stale && "opacity-60",
      )}
    >
      <span className="flex shrink-0 items-center gap-1.5 self-center">
        <Badge variant={stale ? "muted" : variant} appearance="status">
          {label}
        </Badge>
        {stale && (
          <span className="font-mono text-[10.5px] uppercase tracking-[0.06em] text-muted-foreground">
            stale — re-judge
          </span>
        )}
      </span>
      <span className="min-w-0 flex-1 text-foreground">{reason}</span>
    </div>
  );
}
