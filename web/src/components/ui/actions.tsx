import { useState } from "react";
import { AnimatePresence, m } from "motion/react";
import type * as React from "react";
import { AlarmClock, EyeOff, MessageCircleQuestion, Undo2 } from "lucide-react";
import type { Action, ItemDecision, Move, MovePlayer, Pickup, Stat, TaskVerdict, Urgency } from "@/lib/api";
import { SNOOZES } from "@/lib/snooze";
import { askAssistant } from "@/lib/screen";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { CardNote } from "@/components/ui/state";
import { Verdict } from "@/components/ui/verdict";
import { moment } from "@/lib/format";
import { decisionTone, toneText, type Variant } from "@/lib/tone";
import { clickable } from "@/lib/clickable";
import { collapse, pressableRow } from "@/lib/motion";
import { cn } from "@/lib/utils";
import type { Comparing } from "@/components/ui/compare";
import { Label, Meta } from "@/components/ui/label";
import { Disclosure } from "@/components/ui/disclosure";
import { Linked } from "@/components/ui/stat";
import { Table, Td, Th } from "@/components/ui/table";
import { Hint } from "@/components/ui/tooltip";

/** Said in words as well as color, so the order survives without the hue. */
const URGENCY: Record<Urgency, { label: string; variant: Variant }> = {
  now: { label: "Now", variant: "warn" },
  soon: { label: "Soon", variant: "info" },
  later: { label: "Later", variant: "muted" },
};

/** What an add is for, in the corner beside its deadline. */
const PICKUP: Record<Pickup, string> = {
  streamer: "Streamer",
  keeper: "Keeper",
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
 * server where the item has changed since. An agreement is a chip beside the
 * row's controls: the row already says the move and its numbers, and a
 * sentence agreeing with them says them again. Only an overrule or a wait
 * carries the model's reason. A stale verdict is faded; the caller says it is
 * stale once, in `aside`, rather than on every row. `suggested` are the moves
 * the model added that the list did not hold.
 *
 * Items the manager dismissed or snoozed are kept out of the list but not out
 * of reach: they collect under a closed "Hidden" at the foot, each with a way
 * back. A dismissed item that has changed since is back in the list, saying so.
 */
export function ActionList({
  actions,
  suggested = [],
  onOpen,
  onCompare,
  onDecide,
  deciding = false,
  aside,
  footer,
  detail,
}: {
  actions: Action[];
  suggested?: Move[];
  onOpen?: (id: string) => void;
  /** Where an item weighs players against each other: open them side by side rather than one alone. */
  onCompare?: (comparing: Comparing) => void;
  /** Dismiss, snooze or restore an item; absent where decisions cannot be kept. */
  onDecide?: (decision: ItemDecision) => void;
  deciding?: boolean;
  /** Beside the count in the header — where the week puts its Judge control. */
  aside?: React.ReactNode;
  /** Under each row, for what a caller hangs off an item; handed the row's own controls to place. */
  footer?: (action: Action, controls: React.ReactNode) => React.ReactNode;
  /** Inside a row, under its reason: what only the caller can fetch about the item — the best trade on offer. */
  detail?: (action: Action) => React.ReactNode;
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
      {count === 0 && (
        <CardNote>
          {hidden.length
            ? "Nothing left. The rest is hidden below."
            : "Nothing to do."}
        </CardNote>
      )}
      {/* Kept mounted when empty, so the last item dismissed closes up like
          any other rather than vanishing with its list. Not on arrival: the
          list is the first thing read, and is there at once. */}
      <ol className="flex flex-col">
        <AnimatePresence initial={false}>
          {shown.map((action) => {
            const controls = onDecide && action.key && (
              <Decide action={action} onDecide={onDecide} busy={deciding} />
            );
            const below = footer ? footer(action, controls) : controls;
            const agreed = action.verdict?.decision === "AGREE";
            return (
              <Row
                key={action.key || `${action.kind}-${action.title}`}
                badge={URGENCY[action.urgency]}
                title={action.title}
                reason={action.reason}
                when={action.when}
                pickup={action.pickup}
                chance={action.chance}
                evidence={action.evidence}
                players={action.players}
                detail={detail?.(action)}
                open={opener(action, onOpen, onCompare)}
              >
                {action.mark.resurfaced && (
                  <Label as="div" className="mb-1.5">
                    back: changed since dismissed
                  </Label>
                )}
                {action.verdict && !agreed && <VerdictLine verdict={action.verdict} stale={action.stale} />}
                {agreed ? (
                  <span className="flex flex-wrap items-center gap-2">
                    <Agreed stale={action.stale} />
                    {below}
                  </span>
                ) : (
                  below
                )}
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
              {move.metric && <Meta as="div" className="-mt-2">{move.metric}</Meta>}
            </Row>
          ))}
        </AnimatePresence>
      </ol>
      {hidden.length > 0 && <Hidden actions={hidden} onDecide={onDecide} busy={deciding} />}
    </Card>
  );
}

/**
 * What a click on an item opens: the players it weighs, side by side, where
 * it weighs more than one — a start-over-sit or an add-and-drop is a choice
 * between them, and one drawer of one of them shows half of it — or else the
 * player it is about.
 */
export function opener(
  action: Action,
  onOpen?: (id: string) => void,
  onCompare?: (comparing: Comparing) => void,
): (() => void) | undefined {
  const players = action.players.filter((player) => player.player_id);
  const ids = [...new Set(players.map((player) => player.player_id))];
  if (ids.length > 1 && onCompare) {
    const tags = Object.fromEntries(players.map((player) => [player.player_id, player.side === "in" ? "In" : "Out"]));
    return () => onCompare({ ids, title: action.title, tags });
  }
  return action.player_id && onOpen ? () => onOpen(action.player_id) : undefined;
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
        label="Dismiss until it changes"
        icon={<EyeOff />}
        disabled={busy}
        onClick={() => onDecide({ key: action.key, decision: "dismiss", fingerprint: action.fingerprint })}
      />
      <IconButton
        label={choosing ? "Cancel" : "Snooze"}
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
    <Disclosure summary={`Hidden (${actions.length})`}>
      <ul className="flex flex-col pb-1">
        <AnimatePresence initial={false}>
          {actions.map((action) => (
            <m.li
              key={action.key}
              layout="position"
              variants={collapse}
              initial="hidden"
              animate="shown"
              exit="gone"
            >
              {/* The padding inside, so the row can close to nothing. */}
              <div className="flex items-center gap-3 px-4 py-1.5 text-[12.5px]">
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{action.title}</span>
                <Meta className="shrink-0">
                  {action.mark.hidden === "snoozed" && action.mark.snoozed_until
                    ? `snoozed until ${moment(action.mark.snoozed_until)}`
                    : "dismissed"}
                </Meta>
                {onDecide && (
                  <IconButton
                    label="Restore"
                    icon={<Undo2 />}
                    disabled={busy}
                    onClick={() => onDecide({ key: action.key, decision: "restore" })}
                  />
                )}
              </div>
            </m.li>
          ))}
        </AnimatePresence>
      </ul>
    </Disclosure>
  );
}

function Row({
  badge,
  title,
  reason,
  when,
  pickup = null,
  chance = null,
  evidence = [],
  players = [],
  detail,
  open,
  children,
}: {
  badge: { label: string; variant: Variant };
  title: string;
  reason: string;
  when: string;
  /** For an add, whether he streams this week or is kept for the season. */
  pickup?: Pickup | null;
  /** What the move does to the chance of winning, where it was simulated. */
  chance?: Stat | null;
  evidence?: Action["evidence"];
  /** Who the move brings in and takes out, compared figure by figure; empty where it moves one player. */
  players?: MovePlayer[];
  detail?: React.ReactNode;
  open?: () => void;
  children?: React.ReactNode;
}) {
  return (
    // The badge's width, shared with the indent that lines a row's verdict up under its title.
    // Closes up as it leaves the list and opens as it returns; moves, rather
    // than jumps, to a new place when the list is reordered.
    <m.li
      layout="position"
      variants={collapse}
      initial="hidden"
      animate="shown"
      exit="gone"
      className="border-t border-border [--badge-column:5.5rem] first:border-t-0"
    >
      <div
        {...clickable(open)}
        className={cn(
          "flex flex-col items-start gap-1.5 px-4 py-3 sm:flex-row sm:gap-3",
          open && ["cursor-pointer hover:bg-muted", pressableRow],
        )}
      >
        {/* Over the title on a phone: as a column of its own it took a quarter of the width. */}
        <Badge variant={badge.variant} appearance="status" className="mt-0.5 shrink-0 sm:w-(--badge-column)">
          {badge.label}
        </Badge>
        {/* Beside the title on a wide screen; under it on a phone, where a
            corner column squeezes the title to a word a line. */}
        <div className="grid w-full min-w-0 flex-1 grid-cols-1 sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-x-3">
          <div className="text-[13.5px] font-medium">{title}</div>
          {(when || chance || pickup) && (
            <Meta className="flex flex-wrap gap-x-2 pt-0.5 sm:row-span-2 sm:max-w-[11rem] sm:flex-col sm:flex-nowrap sm:items-end sm:gap-0.5 sm:text-right">
              {/* The sign is in the words; the color only lets a cost be found at a glance. */}
              {chance && <span className={cn("font-semibold", toneText(chance.tone))}>{chance.value}</span>}
              {pickup && <span className="font-medium text-foreground">{PICKUP[pickup]}</span>}
              {when}
            </Meta>
          )}
          <div className="min-w-0 sm:col-start-1">
            <div className="mt-0.5 text-[12.5px] text-muted-foreground">{reason}</div>
            {players.length > 1 && <Compared players={players} />}
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
                      <span className="font-medium text-foreground">{line.label}</span>{" "}
                      <Linked url={line.url}>{line.value}</Linked>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {detail && <div className="mt-1.5">{detail}</div>}
          </div>
        </div>
      </div>
      {/* Outside the clickable area: a verdict or a thread is read, not opened. */}
      {children && <div className="px-4 pb-3 sm:pl-[calc(var(--badge-column)+1.75rem)]">{children}</div>}
    </m.li>
  );
}

/**
 * The players a move swaps, side by side: one column each, one row per figure.
 *
 * The server sends every player the same rows in the same order, so a row
 * is read across rather than two sentences being read and held in the head.
 * In and out are said in words over each column; a tone colors only a
 * figure whose words already say what it means — an easy matchup, a status.
 */
export function Compared({ players }: { players: MovePlayer[] }) {
  const rows = players[0]?.figures.map((figure) => figure.label) ?? [];
  // A label that is the app's own measure says what it means on hover and focus.
  const hints = Object.fromEntries((players[0]?.figures ?? []).map((figure) => [figure.label, figure.hint]));
  return (
    <Table className="mt-2 w-auto text-[12px]">
      <thead>
        <tr>
          <Th className="px-0 py-1.5" />
          {players.map((player) => (
            <Th key={`${player.side}-${player.player_id}`} className="px-3 py-1.5 align-bottom">
              <span className="block">{player.side === "in" ? "In" : "Out"}</span>
              <span className="block truncate font-sans text-[12.5px] font-medium normal-case tracking-normal text-foreground">
                {player.name}
              </span>
              <span className="block font-normal normal-case tracking-normal">{player.held}</span>
            </Th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((label, i) => (
          <tr key={label}>
            <Td className="whitespace-nowrap px-0 py-1 font-mono text-[11px] text-muted-foreground">
              {hints[label] ? (
                <Hint label={hints[label]} name={`${label}: ${hints[label]}`} dotted>
                  {label}
                </Hint>
              ) : (
                label
              )}
            </Td>
            {players.map((player) => {
              const figure = player.figures[i];
              return (
                <Td
                  key={`${player.side}-${player.player_id}`}
                  className={cn("px-3 py-1 font-mono", toneText(figure?.tone ?? "neutral", "text-foreground"))}
                >
                  {figure?.value ?? "—"}
                </Td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </Table>
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
      noted={false}
    />
  );
}

/** An agreement, as a chip alone: faded and muted where it was about the item as it was. */
function Agreed({ stale }: { stale: boolean }) {
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
