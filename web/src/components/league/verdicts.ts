/**
 * The model's word on the to-do list: a verdict under the item it is about, an
 * agreement as a chip, whether any of them is stale, and "Why?" to ask more.
 */
import type { Html } from "@effect/ui/html";
import { AssistantProviderMessage } from "@/components/league/assistant-provider";
import { Badge } from "@/components/ui/badge";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Verdict } from "@/components/ui/verdict";
import { decisionTone } from "@/lib/tone";
import type { Action, TaskVerdict } from "@/lib/types";
import { cn } from "@/lib/utils";

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
export function VerdictLine<M>(h: Html.H<M>, { verdict, stale }: { verdict: TaskVerdict; stale: boolean }) {
  return Verdict(h, {
    label: DECISION_LABEL[verdict.decision],
    variant: decisionTone(verdict.decision),
    reason: verdict.reason,
    stale,
    noted: false,
  });
}

/** An agreement, as a chip alone: faded and muted where it was about the item as it was. */
export function Agreed<M>(h: Html.H<M>, { stale }: { stale: boolean }) {
  return Badge(h, {
    variant: stale ? "muted" : decisionTone("AGREE"),
    appearance: "status",
    class: cn(stale && "opacity-60"),
  }).children(DECISION_LABEL.AGREE);
}

/** Whether any verdict on the list was about an item that has changed since: one notice covers them all. */
export function staleVerdicts(actions: readonly Action[]): boolean {
  return actions.some((action) => action.verdict && action.stale && !action.mark.hidden);
}

/**
 * The question "Why?" hands the assistant about one to-do item, with the item
 * as what it is about: sent to `AssistantProvider` by whoever draws the button.
 */
export function askWhy(action: Pick<Action, "key" | "title">) {
  return AssistantProviderMessage.RequestedAsk({
    message: `Why "${action.title}", and what would change your mind?`,
    about: [{ subject: { kind: "task", key: action.key }, label: action.title }],
  });
}

/**
 * "Why?" under a to-do item: asked of the assistant, about that item.
 *
 * The assistant docked in the corner rather than a conversation in the row,
 * so asking about one move and then about the player it turns on, or the
 * waiver wire, is one conversation rather than three. `onClick` is the
 * caller's message, whose `update` sends `askWhy(action)` to the provider;
 * `key` tells one row's button from the next.
 */
export function WhyButton<M>(h: Html.H<M>, { key, onClick }: { key: string; onClick: M }) {
  return IconButton(h, {
    key,
    props: { label: "Why this move?", icon: "message-circle-question" },
    onEmit: { Clicked: () => onClick },
  });
}
