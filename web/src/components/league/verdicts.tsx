/**
 * The model's word on the to-do list: a verdict under the item it is about, an
 * agreement as a chip, whether any of them is stale, and "Why?" to ask more.
 */
import type * as React from "react";
import { MessageCircleQuestion } from "lucide-react";
import type { Action, TaskVerdict } from "@/lib/types";
import { askAssistant } from "@/lib/asking";
import { decisionTone } from "@/lib/tone";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Verdict } from "@/components/ui/verdict";

const DECISION_LABEL: Record<TaskVerdict["decision"], string> = {
  AGREE: "Agree",
  OVERRULE: "Overrule",
  WAIT: "Wait for news",
};

/**
 * The model's word on one item, under the item it is about.
 *
 * Inside the row rather than in a list of its own: an overrule only means
 * something next to the move it overrules.
 */
export function VerdictLine({ verdict, stale }: { verdict: TaskVerdict; stale: boolean }) {
  return (
    <Verdict
      label={DECISION_LABEL[verdict.decision]}
      variant={decisionTone(verdict.decision)}
      reason={verdict.reason}
      stale={stale}
      noted={false}
    />
  );
}

/** An agreement, as a chip alone: faded and muted where it was about the item as it was. */
export function Agreed({ stale }: { stale: boolean }) {
  return (
    <Badge variant={stale ? "muted" : decisionTone("AGREE")} appearance="status" className={cn(stale && "opacity-60")}>
      {DECISION_LABEL.AGREE}
    </Badge>
  );
}

/** Whether any verdict on the list was about an item that has changed since: one notice covers them all. */
export function staleVerdicts(actions: Action[]): boolean {
  return actions.some((action) => action.verdict && action.stale && !action.mark.hidden);
}

/**
 * "Why?" under a to-do item: asked of the assistant, about that item.
 *
 * The assistant docked in the corner rather than a conversation in the row,
 * so asking about one move and then about the player it turns on, or the
 * waiver wire, is one conversation rather than three.
 */
export function WhyButton({
  action,
  beside,
}: {
  action: Action;
  /** On the same line as the Why? control — the row's other controls. */
  beside?: React.ReactNode;
}) {
  return (
    <span className="flex flex-wrap items-center gap-1">
      <IconButton
        label="Why this move?"
        icon={<MessageCircleQuestion />}
        onClick={() =>
          askAssistant(`Why "${action.title}", and what would change your mind?`, [
            { subject: { kind: "task", key: action.key }, label: action.title },
          ])
        }
      />
      {beside}
    </span>
  );
}
