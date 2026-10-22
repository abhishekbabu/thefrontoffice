import { useState } from "react";
import type * as React from "react";
import { AlarmClock, EyeOff, MessageCircleQuestion, Undo2 } from "lucide-react";
import type { Action, ItemDecision, Move, MoveAction, TaskVerdict, Urgency } from "@/lib/api";
import { SNOOZES, until } from "@/lib/snooze";
import { Thread } from "@/components/ui/chat";
import { IconButton } from "@/components/ui/icon-button";
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
 * What to do about the week, most urgent first — and, once judged, what the
 * model makes of each item, inside the item.
 *
 * At the top because it is the reason to open the page: the lineups below are
 * the evidence, and this is the conclusion. Each row names its deadline where
 * the platform has one and opens the player it turns on. An empty list is
 * said out loud — "nothing to do" is an answer worth having, and a missing
 * card would look the same as a page that never checked.
 *
 * `judged` are the same items as the model last saw them. A verdict is shown
 * on the row with the same key, and marked stale where the row has changed
 * since — a verdict on last night's news is not a verdict on this morning's.
 * `suggested` are the moves the model added that the list did not hold.
 *
 * Items the manager dismissed or snoozed are kept out of the list but not out
 * of reach: they collect under a closed "Hidden" at the foot, each with a way
 * back. A dismissed item that has changed since is back in the list, saying so.
 */
export function ActionList({
  actions,
  judged = [],
  suggested = [],
  onOpen,
  onDecide,
  deciding = false,
  aside,
  footer,
}: {
  actions: Action[];
  judged?: Action[];
  suggested?: Move[];
  onOpen?: (id: string) => void;
  /** Dismiss, snooze or restore an item; absent where decisions cannot be kept. */
  onDecide?: (decision: ItemDecision) => void;
  deciding?: boolean;
  /** Beside the count in the header — where the week puts its Judge control. */
  aside?: React.ReactNode;
  /** Under each row, for what a caller hangs off an item; handed the row's own controls to place. */
  footer?: (action: Action, controls: React.ReactNode) => React.ReactNode;
}) {
  const byKey = new Map(judged.filter((task) => task.key).map((task) => [task.key, task]));
  const shown = actions.filter((action) => !action.hidden);
  const hidden = actions.filter((action) => action.hidden);
  const count = shown.length + suggested.length;
  return (
    <Card>
      <CardHeader>
        <span>To do</span>
        <span className="flex items-center gap-3">
          {aside}
          {count > 0 && <span>{count}</span>}
        </span>
      </CardHeader>
      {count === 0 ? (
        <p className="px-4 py-3 text-[13px] text-muted-foreground">
          {hidden.length
            ? "Nothing left to do — the rest is hidden below."
            : "Nothing to do — your lineup is set for the week."}
        </p>
      ) : (
        <ol className="flex flex-col">
          {shown.map((action) => {
            const then = byKey.get(action.key);
            const verdict = then?.verdict ?? action.verdict;
            const controls = onDecide && action.key && (
              <Decide action={action} onDecide={onDecide} busy={deciding} />
            );
            return (
              <Row
                key={action.key || `${action.kind}-${action.title}`}
                badge={URGENCY[action.urgency]}
                title={action.title}
                reason={action.reason}
                when={action.when}
                evidence={action.evidence}
                open={action.player_id && onOpen ? () => onOpen(action.player_id) : undefined}
              >
                {action.resurfaced && (
                  <div className="mb-1.5 font-mono text-[10.5px] uppercase tracking-[0.06em] text-muted-foreground">
                    back — changed since you dismissed it
                  </div>
                )}
                {verdict && <VerdictLine verdict={verdict} stale={Boolean(then) && then?.fingerprint !== action.fingerprint} />}
                {footer ? footer(action, controls) : controls}
              </Row>
            );
          })}
          {suggested.map((move, i) => (
            <Row
              key={`suggested-${move.player}-${i}`}
              badge={{ label: "Suggested", variant: "info" }}
              title={moveTitle(move)}
              reason={move.rationale}
              when={move.metric}
            />
          ))}
        </ol>
      )}
      {hidden.length > 0 && <Hidden actions={hidden} onDecide={onDecide} busy={deciding} />}
    </Card>
  );
}

/**
 * Dismiss or snooze one item. Dismiss hides it until it changes; snooze
 * offers how long, inline — three choices do not need a menu.
 */
function Decide({
  action,
  onDecide,
  busy,
}: {
  action: Action;
  onDecide: (decision: ItemDecision) => void;
  busy: boolean;
}) {
  const [choosing, setChoosing] = useState(false);
  return (
    <span className="flex flex-wrap items-center gap-1">
      <IconButton
        label="Dismiss — hide it until it changes"
        icon={<EyeOff />}
        disabled={busy}
        onClick={() => onDecide({ key: action.key, decision: "dismiss", fingerprint: action.fingerprint })}
      />
      <IconButton
        label={choosing ? "Keep it on the list" : "Snooze"}
        icon={<AlarmClock />}
        disabled={busy}
        aria-expanded={choosing}
        onClick={() => setChoosing((open) => !open)}
      />
      {choosing &&
        SNOOZES.map((snooze) => (
          <button
            key={snooze.label}
            type="button"
            disabled={busy}
            onClick={() => {
              setChoosing(false);
              onDecide({ key: action.key, decision: "snooze", until: snooze.until(new Date()).toISOString() });
            }}
            className="h-7 rounded-md border border-border px-2 font-mono text-[11px] text-muted-foreground hover:bg-muted"
          >
            {snooze.label}
          </button>
        ))}
    </span>
  );
}

/** Items put aside, closed by default, each with a way back. */
function Hidden({
  actions,
  onDecide,
  busy,
}: {
  actions: Action[];
  onDecide?: (decision: ItemDecision) => void;
  busy: boolean;
}) {
  return (
    <details className="border-t border-border">
      <summary className="cursor-pointer px-4 py-2.5 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground hover:text-foreground">
        Hidden ({actions.length})
      </summary>
      <ul className="flex flex-col pb-1">
        {actions.map((action) => (
          <li key={action.key} className="flex items-center gap-3 px-4 py-1.5 text-[12.5px]">
            <span className="min-w-0 flex-1 truncate text-muted-foreground">{action.title}</span>
            <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
              {action.hidden === "snoozed" && action.snoozed_until ? `snoozed until ${until(action.snoozed_until)}` : "dismissed"}
            </span>
            {onDecide && (
              <IconButton
                label="Put it back on the list"
                icon={<Undo2 />}
                disabled={busy}
                onClick={() => onDecide({ key: action.key, decision: "restore" })}
              />
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

function Row({
  badge,
  title,
  reason,
  when,
  evidence = [],
  open,
  children,
}: {
  badge: { label: string; variant: "warn" | "info" | "muted" };
  title: string;
  reason: string;
  when: string;
  evidence?: Action["evidence"];
  open?: () => void;
  children?: React.ReactNode;
}) {
  return (
    <li className="border-t border-border first:border-t-0">
      <div
        onClick={open}
        onKeyDown={open && ((e) => e.key === "Enter" && open())}
        tabIndex={open ? 0 : undefined}
        role={open ? "button" : undefined}
        className={cn("flex items-start gap-3 px-4 py-3", open && "cursor-pointer hover:bg-muted")}
      >
        <Badge variant={badge.variant} appearance="status" className="mt-0.5 w-[5.5rem] shrink-0">
          {badge.label}
        </Badge>
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-medium">{title}</div>
          <div className="mt-0.5 text-[12.5px] text-muted-foreground">{reason}</div>
          {evidence.length > 0 && (
            <ul className="mt-1.5 flex flex-col gap-1">
              {evidence.map((line, i) => (
                <li key={`${line.label}-${i}`} className="flex items-baseline gap-2 text-[12px] text-muted-foreground">
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
        {when && (
          <span className="max-w-[11rem] shrink-0 pt-0.5 text-right font-mono text-[11px] text-muted-foreground">
            {when}
          </span>
        )}
      </div>
      {/* Outside the clickable area: a verdict or a thread is read, not opened. */}
      {children && <div className="px-4 pb-3 pl-[calc(5.5rem+1.75rem)]">{children}</div>}
    </li>
  );
}

const MOVE_VERB: Record<MoveAction, string> = {
  ADD: "Add",
  DROP: "Drop",
  START: "Start",
  BENCH: "Bench",
  TRANSFER: "Bring in",
  CAPTAIN: "Captain",
  MONITOR: "Watch",
};

const MOVE_JOIN: Partial<Record<MoveAction, string>> = {
  ADD: "drop",
  START: "over",
  TRANSFER: "for",
  BENCH: "for",
};

/** "Add Jaylen Warren, drop Roschon Johnson" — the model's move as the list phrases its own. */
function moveTitle(move: Move): string {
  const join = MOVE_JOIN[move.action];
  const rest = move.replaces && join ? (join === "drop" ? `, drop ${move.replaces}` : ` ${join} ${move.replaces}`) : "";
  return `${MOVE_VERB[move.action]} ${move.player}${rest}`;
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
 * something next to the move it overrules. A stale one stays, faded and
 * labelled — the reasoning may still hold, but it was about something else.
 */
function VerdictLine({ verdict, stale }: { verdict: TaskVerdict; stale: boolean }) {
  return (
    <div className={cn("flex items-baseline gap-2 rounded-md bg-muted px-2.5 py-1.5 text-[12.5px]", stale && "opacity-60")}>
      <Badge variant={stale ? "muted" : decisionTone(verdict.decision)} appearance="status" className="shrink-0">
        {DECISION_LABEL[verdict.decision]}
      </Badge>
      <span className="text-foreground">{verdict.reason}</span>
      {stale && (
        <span className="ml-auto shrink-0 font-mono text-[10.5px] uppercase tracking-[0.06em] text-muted-foreground">
          stale — re-judge
        </span>
      )}
    </div>
  );
}

/**
 * "Why?" under a to-do item: a conversation about that item alone.
 *
 * Mounted on first open and only hidden after, so closing it and opening it
 * again shows the same conversation instead of a blank one.
 */
export function WhyThread({
  competition,
  league,
  action,
  beside,
}: {
  competition: string;
  league: string;
  action: Action;
  /** On the same line as the Why? control — the row's other controls. */
  beside?: React.ReactNode;
}) {
  const [opened, setOpened] = useState(false);
  const [shown, setShown] = useState(false);
  return (
    <div className="flex flex-col gap-2">
      <span className="flex flex-wrap items-center gap-1">
        <IconButton
          label={shown ? "Hide the conversation" : "Why this move?"}
          icon={<MessageCircleQuestion />}
          onClick={() => {
            setOpened(true);
            setShown((s) => !s);
          }}
          aria-expanded={shown}
        />
        {beside}
      </span>
      {opened && (
        <div className={cn("rounded-md border border-border p-3", !shown && "hidden")}>
          <Thread
            competition={competition}
            league={league}
            subject={{ kind: "task", key: action.key }}
            opener="Why this move — and what would change your mind?"
            placeholder="Ask about this move"
            bare
          />
        </div>
      )}
    </div>
  );
}
