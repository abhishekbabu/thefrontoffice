import { Command, Component, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Clock, Effect, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { AssistantProvider } from "@/components/league/assistant-provider";
import { BestTrade } from "@/components/league/best-trade";
import { Row, rowName } from "@/components/league/action-row";
import { Agreed, VerdictLine, WhyButton, askWhy } from "@/components/league/verdicts";
import { Card, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/controls/button";
import { IconButton } from "@/components/ui/controls/icon-button";
import { ErrorNote } from "@/components/ui/error-note";
import { Label, Meta } from "@/components/ui/label";
import { Disclosure } from "@/components/ui/overlays/disclosure";
import { CardNote } from "@/components/ui/state";
import { ApiError, api } from "@/lib/api";
import type { Comparing } from "@/lib/comparing";
import { fetching } from "@/lib/queries/cache";
import { GetWeek } from "@/lib/queries/week";
import { SNOOZES } from "@/lib/snooze";
import { moment } from "@/lib/times";
import type { Variant } from "@/lib/tone";
import type { Action, Competition, Move, Summary, Urgency } from "@/lib/types";
import { offers } from "@/lib/views";
import { wire } from "@/lib/wire";

/** Said in words as well as color, so the order survives without the hue. */
const URGENCY: Record<Urgency, { label: string; variant: Variant }> = {
  now: { label: "Now", variant: "warn" },
  soon: { label: "Soon", variant: "info" },
  later: { label: "Later", variant: "muted" },
};

/**
 * The view-transition type of the update that puts an item aside or brings it
 * back (`::view-transition-group(*.row)` in index.css): the rows close up and
 * open, rather than the list jumping.
 */
const ROW_TRANSITION = "row";

/** `RequestedOpenPlayer`: open the player an item is about. `RequestedCompare`: open the players it weighs, side by side. */
export const ActionListEvents = UiSchema.TaggedEnum({
  RequestedOpenPlayer: { id: Schema.String },
  RequestedCompare: { comparing: wire<Comparing>() },
});

const Decision = Schema.Literals(["dismiss", "snooze", "restore"]);

const ActionListMessage = UiSchema.TaggedEnum({
  ClickedPlayer: { id: Schema.String },
  ClickedCompare: { comparing: wire<Comparing>() },
  RequestedCompareBestTrade: { comparing: wire<Comparing>() },
  ClickedWhy: { key: Schema.String, title: Schema.String },
  ClickedDismiss: { key: Schema.String, fingerprint: Schema.String },
  ClickedSnooze: { key: Schema.String },
  ClickedSnoozeFor: { key: Schema.String, label: Schema.String },
  ClickedRestore: { key: Schema.String },
  /** The week as it reads with the item's new mark, or null where nothing on the page had read it. */
  SucceededDecideItem: { week: Schema.NullOr(wire<Summary>()) },
  FailedDecideItem: { error: ApiError },
});

/**
 * Dismisses, snoozes or restores one item. The server answers with the
 * item's new mark, which goes straight onto its row in the week: re-reading
 * the week would take a second or two for one field. A snooze is measured
 * from now on the viewer's own clock — "tomorrow morning" means their
 * morning — and sent with its offset, which keeps it in UTC.
 */
class DecideItem extends Command.Service<DecideItem>()("actions/DecideItem", {
  args: {
    competition: Schema.String,
    league: Schema.String,
    key: Schema.String,
    decision: Decision,
    fingerprint: Schema.optional(Schema.String),
    /** For a snooze: which of `SNOOZES` was picked, by its label. */
    snooze: Schema.optional(Schema.String),
  },
  success: ActionListMessage,
  // Covers the write, which stores the week fresh rather than asking for it again.
  invalidates: ({ competition, league }) => [GetWeek.entry({ competition, league })],
  writes: (message, { competition, league }) =>
    message._tag === "SucceededDecideItem" && message.week !== null
      ? [GetWeek.set({ competition, league }, message.week)]
      : [],
}) {
  static readonly layer = this.toLayer(({ competition, league, key, decision, fingerprint, snooze }) =>
    Effect.gen(function* () {
      const now = new Date(yield* Clock.currentTimeMillis);
      const until = SNOOZES.find((choice) => choice.label === snooze)?.until(now).toISOString() ?? null;

      const mark = yield* fetching(() =>
        api.league(competition, league).decide({ key, decision, fingerprint: fingerprint ?? "", until }),
      );

      const week = yield* GetWeek.peek({ competition, league });

      if (!AsyncResult.isSuccess(week) || !week.value.actions) return null;

      return {
        ...week.value,
        actions: week.value.actions.map((action) => (action.key === key ? { ...action, mark } : action)),
      };
    }).pipe(
      Effect.match({
        onSuccess: (week) => ActionListMessage.SucceededDecideItem({ week }),
        onFailure: (error) => ActionListMessage.FailedDecideItem({ error }),
      }),
    ),
  );
}

export const ActionListProps = Schema.Struct({
  /** The league the list is about, by key and id: what a decision is kept against. */
  competition: wire<Competition>(),
  league: Schema.String,
  actions: Schema.Array(wire<Action>()),
  /** The moves the model added that the list did not hold. */
  suggested: Schema.optional(Schema.Array(wire<Move>())),
  /** Whether an item can be dismissed, snoozed or restored; false where decisions cannot be kept. */
  decides: Schema.optional(Schema.Boolean),
  /** Whether each item offers "Why?" of the assistant: only where a model is configured. */
  asks: Schema.optional(Schema.Boolean),
});

export type ActionListProps = typeof ActionListProps.Type;

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
 * stale once, in the `aside` slot — beside the count in the header, where the
 * week puts its Judge control — rather than on every row.
 *
 * A trade item carries the best trade on offer, where the competition finds
 * trades. Items the manager dismissed or snoozed are kept out of the list but
 * not out of reach: they collect under a closed "Hidden" at the foot, each
 * with a way back. A dismissed item that has changed since is back in the
 * list, saying so.
 */
const ActionListNoDeps = Html.component({
  name: "ActionList",
  props: ActionListProps,
  model: Schema.Struct({
    /** The items whose snooze choices are open. */
    choosing: Schema.Array(Schema.String),
    failed: Schema.NullOr(ApiError),
  }),
  message: ActionListMessage,
  events: ActionListEvents,
  slots: ["aside"],
  reads: { assistant: { owner: AssistantProvider, optional: true } },
  restore: false,
}).make({
  init: () => ({ choosing: [], failed: null }),
  update: ($, message) => {
    const decide = (key: string, decision: typeof Decision.Type, extra: { fingerprint?: string; snooze?: string }) =>
      DecideItem.make({ competition: $.props.competition.key, league: $.props.league, key, decision, ...extra });

    return ActionListMessage.match(message, {
      ClickedPlayer: ({ id }) => $.emit(ActionListEvents.RequestedOpenPlayer({ id })),
      ClickedCompare: ({ comparing }) => $.emit(ActionListEvents.RequestedCompare({ comparing })),
      RequestedCompareBestTrade: ({ comparing }) => $.emit(ActionListEvents.RequestedCompare({ comparing })),
      ClickedWhy: ({ key, title }) => $.send(AssistantProvider, askWhy({ key, title })),
      ClickedDismiss: ({ key, fingerprint }) => $.run(decide(key, "dismiss", { fingerprint })),
      ClickedSnooze: ({ key }) =>
        $.evolve({ choosing: (open) => (open.includes(key) ? open.filter((k) => k !== key) : [...open, key]) }),
      ClickedSnoozeFor: ({ key, label }) =>
        $.evolve({ choosing: (open) => open.filter((k) => k !== key) }).run(decide(key, "snooze", { snooze: label })),
      ClickedRestore: ({ key }) => $.run(decide(key, "restore", {})),
      // The row closes up as it leaves the list and opens as it returns; the
      // rest move, rather than jump, to their new places.
      SucceededDecideItem: () => $.evolve({ failed: null }).viewTransition([ROW_TRANSITION]),
      FailedDecideItem: ({ error }) => $.evolve({ failed: error }),
    });
  },
  view: (h, model) => {
    const { actions, suggested = [], decides = false, asks = false, competition } = h.props;
    const busy = h.isRunning(DecideItem);
    const shown = actions.filter((action) => !action.mark.hidden);
    const hidden = actions.filter((action) => action.mark.hidden);
    const count = shown.length + suggested.length;
    const trades = offers(competition, "trades");

    return h.div.class("contents").children(
      model.failed !== null && ErrorNote(h, { error: model.failed, class: "m-0" }),
      Card(h).children(
        CardHeader(h).children(
          h.span("To do"),
          h.span.class("flex items-center gap-3").children(h.slots.aside, count > 0 && h.span(String(count))),
        ),
        count === 0 &&
          CardNote(h).children(hidden.length ? "Nothing left. The rest is hidden below." : "Nothing to do."),
        // Kept mounted when empty, so the last item dismissed closes up like
        // any other rather than vanishing with its list. Not on arrival: the
        // list is the first thing read, and is there at once.
        h.ol.class("flex flex-col").children(
          shown.map((action) => {
            const controls = decides && action.key && Decide(h, { action, busy, choosing: model.choosing.includes(action.key) });

            const below = asks
              ? action.key &&
                h.span
                  .class("flex flex-wrap items-center gap-1")
                  .children(
                    WhyButton(h, {
                      key: `why-${action.key}`,
                      onClick: ActionListMessage.ClickedWhy({ key: action.key, title: action.title }),
                    }),
                    controls,
                  )
              : controls;

            const agreed = action.verdict?.decision === "AGREE";

            return Row(h, {
              key: action.key || `${action.kind}-${action.title}`,
              badge: URGENCY[action.urgency],
              title: action.title,
              reason: action.reason,
              when: action.when,
              pickup: action.pickup,
              chance: action.chance,
              evidence: action.evidence,
              players: action.players,
              detail:
                action.kind === "trade" && trades
                  ? [BestTrade(h, {
                  key: `trade-${action.key}`,
                  props: { competition: competition.key, league: h.props.league },
                  onEmit: {
                    RequestedCompare: ({ comparing }) => ActionListMessage.RequestedCompareBestTrade({ comparing }),
                  },
                })]
                  : undefined,
              open: opener<Message>(
                action,
                (id) => ActionListMessage.ClickedPlayer({ id }),
                (comparing) => ActionListMessage.ClickedCompare({ comparing }),
              ),
              children: [
                action.mark.resurfaced && Label(h, { as: "div", class: "mb-1.5" }).children("back: changed since dismissed"),
                action.verdict && !agreed && VerdictLine(h, { verdict: action.verdict, stale: action.stale }),
                agreed
                  ? h.span.class("flex flex-wrap items-center gap-2").children(Agreed(h, { stale: action.stale }), below)
                  : below,
              ],
            });
          }),
          suggested.map((move, i) =>
            Row(h, {
              key: `suggested-${move.player}-${i}`,
              badge: { label: "Suggested", variant: "info" },
              title: move.title,
              reason: move.rationale,
              when: "",
              // The model's own figure, in its own words — a sentence, not a
              // deadline, so it gets the row's width rather than the corner.
              children: move.metric ? [Meta(h, { as: "div", class: "-mt-2" }).children(move.metric)] : undefined,
            }),
          ),
        ),
        hidden.length > 0 && Hidden(h, { actions: hidden, decides, busy }),
      ),
    );
  },
});

export const ActionList = ActionListNoDeps.pipe(Component.provide(DecideItem.layer));

/**
 * What a click on an item opens: the players it weighs, side by side, where
 * it weighs more than one — a start-over-sit or an add-and-drop is a choice
 * between them, and one drawer of one of them shows half of it — or else the
 * player it is about. The caller's message for either, or nothing to open.
 */
export function opener<M>(
  action: Action,
  onOpen?: (id: string) => M,
  onCompare?: (comparing: Comparing) => M,
): M | undefined {
  const players = action.players.filter((player) => player.player_id);
  const ids = [...new Set(players.map((player) => player.player_id))];

  if (ids.length > 1 && onCompare) {
    const tags = Object.fromEntries(players.map((player) => [player.player_id, player.side === "in" ? "In" : "Out"]));

    return onCompare({ ids, title: action.title, tags });
  }

  return action.player_id && onOpen ? onOpen(action.player_id) : undefined;
}

type Message = typeof ActionListMessage.Type;

/**
 * Dismiss or snooze one item. Dismiss hides it until it changes; snooze
 * offers how long, inline — three choices do not need a menu.
 */
function Decide(h: Html.H<Message>, { action, busy, choosing }: { action: Action; busy: boolean; choosing: boolean }) {
  return h.span.class("flex flex-wrap items-center gap-1").children(
    IconButton(h, {
      key: `dismiss-${action.key}`,
      props: { label: "Dismiss until it changes", icon: "eye-off", disabled: busy },
      onEmit: { Clicked: () => ActionListMessage.ClickedDismiss({ key: action.key, fingerprint: action.fingerprint }) },
    }),
    IconButton(h, {
      key: `snooze-${action.key}`,
      props: { label: choosing ? "Cancel" : "Snooze", icon: "alarm-clock", disabled: busy, expanded: choosing },
      onEmit: { Clicked: () => ActionListMessage.ClickedSnooze({ key: action.key }) },
    }),
    choosing &&
      SNOOZES.map((snooze) =>
        Button(h, { variant: "outline", size: "sm", class: "font-mono text-[11px] text-muted-foreground" })
          .key(snooze.label)
          .disabled(busy)
          .on("click", ActionListMessage.ClickedSnoozeFor({ key: action.key, label: snooze.label }))
          .children(snooze.label),
      ),
  );
}

/** Items put aside, closed by default, each with a way back. */
function Hidden(h: Html.H<Message>, { actions, decides, busy }: { actions: Action[]; decides: boolean; busy: boolean }) {
  return Disclosure(h, {
    summary: [`Hidden (${actions.length})`],
    children: [
      h.ul.class("flex flex-col pb-1").children(
        actions.map((action) =>
          h.li
            .key(action.key)
            .class("[view-transition-class:row]")
            .style({ viewTransitionName: rowName("hidden", action.key) })
            .children(
              h.div.class("flex items-center gap-3 px-4 py-1.5 text-[12.5px]").children(
                h.span.class("min-w-0 flex-1 truncate text-muted-foreground").children(action.title),
                Meta(h, { class: "shrink-0" }).children(
                  action.mark.hidden === "snoozed" && action.mark.snoozed_until
                    ? `snoozed until ${moment(action.mark.snoozed_until)}`
                    : "dismissed",
                ),
                decides &&
                  IconButton(h, {
                    key: `restore-${action.key}`,
                    props: { label: "Restore", icon: "undo-2", disabled: busy },
                    onEmit: { Clicked: () => ActionListMessage.ClickedRestore({ key: action.key }) },
                  }),
              ),
            ),
        ),
      ),
    ],
  });
}
