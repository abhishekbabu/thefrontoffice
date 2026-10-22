import type * as React from "react";
import type { Action, TaskVerdict, Urgency } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { decisionTone } from "@/lib/tone";
import { cn } from "@/lib/utils";

/** Said in words as well as color, so the order survives without the hue. */
const URGENCY: Record<Urgency, { label: string; variant: "warn" | "info" | "muted" }> = {
  now: { label: "Now", variant: "warn" },
  soon: { label: "Soon", variant: "info" },
  later: { label: "Later", variant: "muted" },
};

/**
 * What to do about the week, most urgent first.
 *
 * At the top because it is the reason to open the page: the lineups below are
 * the evidence, and this is the conclusion. Each row names its deadline where
 * the platform has one and opens the player it turns on. An empty list is
 * said out loud — "nothing to do" is an answer worth having, and a missing
 * card would look the same as a page that never checked.
 */
export function ActionList({
  actions,
  onOpen,
  aside,
}: {
  actions: Action[];
  onOpen?: (id: string) => void;
  /** Beside the count in the header — where the week links to a second opinion. */
  aside?: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <span>To do</span>
        <span className="flex items-center gap-3">
          {aside}
          {actions.length > 0 && <span>{actions.length}</span>}
        </span>
      </CardHeader>
      {actions.length === 0 ? (
        <p className="px-4 py-3 text-[13px] text-muted-foreground">Nothing to do — your lineup is set for the week.</p>
      ) : (
        <ol className="flex flex-col">
          {actions.map((action) => {
            const open = action.player_id && onOpen ? () => onOpen(action.player_id) : undefined;
            const urgency = URGENCY[action.urgency];
            return (
              <li
                key={`${action.kind}-${action.title}`}
                onClick={open}
                onKeyDown={open && ((e) => e.key === "Enter" && open())}
                tabIndex={open ? 0 : undefined}
                role={open ? "button" : undefined}
                className={cn(
                  "flex items-start gap-3 border-t border-border px-4 py-3 first:border-t-0",
                  open && "cursor-pointer hover:bg-muted",
                )}
              >
                <Badge variant={urgency.variant} appearance="status" className="mt-0.5 w-16 shrink-0">
                  {urgency.label}
                </Badge>
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px] font-medium">{action.title}</div>
                  <div className="mt-0.5 text-[12.5px] text-muted-foreground">{action.reason}</div>
                  {action.verdict && <VerdictLine verdict={action.verdict} />}
                  {action.evidence.length > 0 && (
                    <ul className="mt-1.5 flex flex-col gap-1">
                      {action.evidence.map((line) => (
                        <li key={line.label} className="flex items-baseline gap-2 text-[12px] text-muted-foreground">
                          {/* The rank is in the words; the dot only lets a
                              soft or tough matchup be found at a glance. */}
                          <span
                            aria-hidden
                            className={cn(
                              "size-1.5 shrink-0 -translate-y-px rounded-full bg-border",
                              line.tone === "good" && "bg-ok",
                              line.tone === "warning" && "bg-warn",
                            )}
                          />
                          <span>
                            <span className="font-medium text-foreground">{line.label}</span> {line.value}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                {action.when && (
                  <span className="shrink-0 pt-0.5 text-right font-mono text-[11px] text-muted-foreground">
                    {action.when}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}


const DECISION_LABEL: Record<TaskVerdict["decision"], string> = {
  AGREE: "Agree",
  OVERRULE: "Overrule",
  WAIT: "Wait for news",
};

/**
 * The model's word on one item, under the item it is about.
 *
 * Inside the row rather than in a list of its own: an overrule only means
 * something next to the move it overrules, and reading two lists in step is
 * the work this layout exists to save.
 */
function VerdictLine({ verdict }: { verdict: TaskVerdict }) {
  return (
    <div className="mt-2 flex items-baseline gap-2 rounded-md bg-muted px-2.5 py-1.5 text-[12.5px]">
      <Badge variant={decisionTone(verdict.decision)} appearance="status" className="shrink-0">
        {DECISION_LABEL[verdict.decision]}
      </Badge>
      <span className="text-foreground">{verdict.reason}</span>
    </div>
  );
}
