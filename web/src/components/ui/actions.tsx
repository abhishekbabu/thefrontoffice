import { useState } from "react";
import type * as React from "react";
import { AlarmClock, EyeOff, MessageCircleQuestion, Undo2 } from "lucide-react";
import type { Action, ItemDecision, Move, Stat, TaskVerdict, Urgency } from "@/lib/api";
import { SNOOZES } from "@/lib/snooze";
import { Thread } from "@/components/ui/chat";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { CardNote } from "@/components/ui/state";
import { Verdict } from "@/components/ui/verdict";
import { moment } from "@/lib/format";
import { decisionTone, toneText, type Variant } from "@/lib/tone";
import { cn } from "@/lib/utils";
import { Label } from "@/components/ui/label";

/** Said in words as well as color, so the order survives without the hue. */
const URGENCY: Record<Urgency, { label: string; variant: Variant }> = {
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
 * Each item arrives with the model's last verdict on it, marked stale by the
 * server where the item has changed since. `suggested` are the moves the
 * model added that the list did not hold.
 *
 * Items the manager dismissed or snoozed are kept out of the list but not out
 * of reach: they collect under a closed "Hidden" at the foot, each with a way
 * back. A dismissed item that has changed since is back in the list, saying so.
 */
export function ActionList({
  actions,
  suggested = [],
  onOpen,
  onDecide,
  deciding = false,
  aside,
  footer,
}: {
  actions: Action[];
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
  const shown = actions.filter((action) => !action.mark.hidden);
  const hidden = actions.filter((action) => action.mark.hidden);
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
        <CardNote>
          {hidden.length
            ? "Nothing left to do — the rest is hidden below."
            : "Nothing to do — your lineup is set for the week."}
        </CardNote>
      ) : (
        <ol className="flex flex-col">
          {shown.map((action) => {
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
                chance={action.chance}
                evidence={action.evidence}
                open={action.player_id && onOpen ? () => onOpen(action.player_id) : undefined}
              >
                {action.mark.resurfaced && (
                  <Label as="div" className="mb-1.5">
                    back — changed since you dismissed it
                  </Label>
                )}
                {action.verdict && <VerdictLine verdict={action.verdict} stale={action.stale} />}
                {footer ? footer(action, controls) : controls}
              </Row>
            );
          })}
          {suggested.map((move, i) => (
            <Row
              key={`suggested-${move.player}-${i}`}
              badge={{ label: "Suggested", variant: "info" }}
              title={move.title}
              reason={move.rationale}
              when=""
            >
              {/* The model's own figure, in its own words — a sentence, not a
                  deadline, so it gets the row's width rather than the corner. */}
              {move.metric && <div className="-mt-2 font-mono text-[11px] text-muted-foreground">{move.metric}</div>}
            </Row>
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
          <Button
            key={snooze.label}
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => {
              setChoosing(false);
              onDecide({ key: action.key, decision: "snooze", until: snooze.until(new Date()).toISOString() });
            }}
            className="font-mono text-[11px] text-muted-foreground"
          >
            {snooze.label}
          </Button>
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
      <Label as="summary" className="cursor-pointer px-4 py-2.5 hover:text-foreground">
        Hidden ({actions.length})
      </Label>
      <ul className="flex flex-col pb-1">
        {actions.map((action) => (
          <li key={action.key} className="flex items-center gap-3 px-4 py-1.5 text-[12.5px]">
            <span className="min-w-0 flex-1 truncate text-muted-foreground">{action.title}</span>
            <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
              {action.mark.hidden === "snoozed" && action.mark.snoozed_until
                ? `snoozed until ${moment(action.mark.snoozed_until)}`
                : "dismissed"}
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
  chance = null,
  evidence = [],
  open,
  children,
}: {
  badge: { label: string; variant: Variant };
  title: string;
  reason: string;
  when: string;
  /** What the move does to the chance of winning, where it was simulated. */
  chance?: Stat | null;
  evidence?: Action["evidence"];
  open?: () => void;
  children?: React.ReactNode;
}) {
  return (
    // The badge's width, shared with the indent that lines a row's verdict up under its title.
    <li className="border-t border-border [--badge-column:5.5rem] first:border-t-0">
      <div
        onClick={open}
        onKeyDown={open && ((e) => e.key === "Enter" && open())}
        tabIndex={open ? 0 : undefined}
        role={open ? "button" : undefined}
        className={cn("flex items-start gap-3 px-4 py-3", open && "cursor-pointer hover:bg-muted")}
      >
        <Badge variant={badge.variant} appearance="status" className="mt-0.5 w-(--badge-column) shrink-0">
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
        {(when || chance) && (
          <span className="flex max-w-[11rem] shrink-0 flex-col items-end gap-0.5 pt-0.5 text-right font-mono text-[11px] text-muted-foreground">
            {/* The sign is in the words; the color only lets a cost be found at a glance. */}
            {chance && <span className={cn("font-semibold", toneText(chance.tone))}>{chance.value}</span>}
            {when}
          </span>
        )}
      </div>
      {/* Outside the clickable area: a verdict or a thread is read, not opened. */}
      {children && <div className="px-4 pb-3 pl-[calc(var(--badge-column)+1.75rem)]">{children}</div>}
    </li>
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
 * something next to the move it overrules.
 */
function VerdictLine({ verdict, stale }: { verdict: TaskVerdict; stale: boolean }) {
  return (
    <Verdict
      label={DECISION_LABEL[verdict.decision]}
      variant={decisionTone(verdict.decision)}
      reason={verdict.reason}
      stale={stale}
    />
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
