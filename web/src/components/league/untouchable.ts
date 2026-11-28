/**
 * The players on your roster you will not let go, in one league, and the way
 * to mark one: never a drop, a trade away or a sale.
 *
 * Kept on the server, because the server is what chooses drops, trade ideas
 * and transfers: a mark changes what the week's to-do list, the trades and
 * the weeks ahead say, so those are read again once it is made. Where your
 * players are listed, `GetUntouchables` says which carry the lock.
 */
import { Command, Component, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Effect, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Icon } from "@/components/ui/icon";
import { Hint } from "@/components/ui/overlays/hint";
import { ApiError, api } from "@/lib/api";
import { fetching, type Answer, type LeagueApi } from "@/lib/queries/cache";
import { GetTrades } from "@/lib/queries/players";
import { GetOutlook, GetRoster, GetUntouchables } from "@/lib/queries/teams";
import { GetWeek } from "@/lib/queries/week";
import { wire } from "@/lib/wire";

const UntouchableToggleMessage = UiSchema.TaggedEnum({
  ClickedToggle: {},
  /** Every untouchable after the mark, as the server answered. */
  SucceededMarkUntouchable: { now: wire<Answer<LeagueApi["untouchables"]>>() },
  FailedMarkUntouchable: { message: Schema.String },
});

/**
 * Marks one player untouchable or clears his mark. The answer is every mark
 * after it, written straight into the list; everything the server chooses
 * around the marks is asked again. Every team's weeks ahead, since the
 * outlook is read per team.
 */
class MarkUntouchable extends Command.Service<MarkUntouchable>()("league/MarkUntouchable", {
  args: { competition: Schema.String, league: Schema.String, player: Schema.String, untouchable: Schema.Boolean },
  success: UntouchableToggleMessage,
  writes: (success, { competition, league }) =>
    success._tag === "SucceededMarkUntouchable" ? [GetUntouchables.set({ competition, league }, success.now)] : [],
  // The list itself too, which the write then leaves fresh rather than asked again.
  invalidates: ({ competition, league }) => [
    GetUntouchables.entry({ competition, league }),
    GetWeek.entry({ competition, league }),
    GetTrades.entry({ competition, league }),
    GetOutlook,
  ],
}) {
  static readonly layer = this.toLayer(({ competition, league, player, untouchable }) =>
    fetching(() => api.league(competition, league).markUntouchable({ player_id: player, untouchable })).pipe(
      Effect.match({
        onSuccess: (now) => UntouchableToggleMessage.SucceededMarkUntouchable({ now }),
        onFailure: (error: ApiError) => UntouchableToggleMessage.FailedMarkUntouchable({ message: error.message }),
      }),
    ),
  );
}

/**
 * Mark one of your players untouchable, or clear the mark. Offered for your
 * own players only — a mark on anyone else's would honour nothing. The lock's
 * shape and the label carry the state.
 *
 * Your own roster is read as the roster page first reads it, in the
 * competition's own order (no sort), so a drawer opened from there asks
 * nothing again.
 */
const UntouchableToggleNoDeps = Html.component({
  name: "UntouchableToggle",
  props: Schema.Struct({ competition: Schema.String, league: Schema.String, player: Schema.String }),
  model: Schema.Struct({ failed: Schema.Boolean }),
  message: UntouchableToggleMessage,
  queries: {
    roster: {
      query: GetRoster,
      args: ({ props }) => (props.player === "" ? undefined : { competition: props.competition, league: props.league }),
    },
    marked: {
      query: GetUntouchables,
      args: ({ props, queries }) =>
        mine(queries.roster, props.player) ? { competition: props.competition, league: props.league } : undefined,
    },
  },
  restore: false,
}).make({
  init: () => ({ failed: false }),
  update: {
    ClickedToggle: ($) =>
      $.evolve({ failed: false }).run(
        MarkUntouchable.make({
          competition: $.props.competition,
          league: $.props.league,
          player: $.props.player,
          untouchable: !marked($.queries.marked, $.props.player),
        }),
      ),
    SucceededMarkUntouchable: ($) => $.evolve({ failed: false }),
    FailedMarkUntouchable: ($) => $.evolve({ failed: true }),
  },
  view: (h, model) => {
    // A view draws something: off your roster, an empty box that takes no room.
    if (!mine(h.queries.roster, h.props.player)) return h.span.class("contents");

    const on = marked(h.queries.marked, h.props.player);

    return IconButton(h, {
      key: "untouchable",
      props: {
        label: model.failed ? "Not saved: try again" : on ? "Untouchable: clear" : "Mark untouchable",
        icon: on ? "lock" : "lock-open",
        pressed: on,
        disabled: h.isRunning(MarkUntouchable),
      },
      onEmit: { Clicked: () => UntouchableToggleMessage.ClickedToggle() },
    });
  },
});

export const UntouchableToggle = UntouchableToggleNoDeps.pipe(Component.provide(MarkUntouchable.layer));

/** Whether `player` is on the roster `roster` holds, once it has loaded. */
function mine(roster: AsyncResult.AsyncResult<Answer<LeagueApi["roster"]>, ApiError>, player: string): boolean {
  return AsyncResult.isSuccess(roster) && roster.value.some((card) => card.player_id === player);
}

/** Whether `player` is marked in the list `untouchables` holds, once it has loaded. */
function marked(untouchables: AsyncResult.AsyncResult<Answer<LeagueApi["untouchables"]>, ApiError>, player: string): boolean {
  return AsyncResult.isSuccess(untouchables) && untouchables.value.player_ids.includes(player);
}

/**
 * The lock beside the name of a player you marked untouchable, wherever your
 * players are listed. `key` tells the locks of one list apart: a row's id.
 */
export function UntouchableLock<M>(h: Html.H<M>, key: string) {
  return Hint(h, {
    key: `untouchable-${key}`,
    props: { label: "Untouchable", name: "Untouchable", class: "inline-flex shrink-0" },
    slots: { content: Icon(h, "lock", { class: "size-3 text-muted-foreground" }) },
  });
}
