import { Command, Component, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Effect, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { Drawers, DrawerState, playerDrawer } from "@/components/league/drawers";
import { LeagueHeader } from "@/components/league/page-header";
import { RosterTable, toOrder } from "@/components/league/rosters/roster-table";
import { Card, CardHeader } from "@/components/ui/card";
import { IconButton } from "@/components/ui/controls/icon-button";
import { SearchInput } from "@/components/ui/controls/input";
import { MARKER, Tabs } from "@/components/ui/controls/tabs";
import { ToggleChip } from "@/components/ui/controls/toggle";
import { SortState } from "@/components/ui/data-table";
import { ErrorNote } from "@/components/ui/error-note";
import { Meta } from "@/components/ui/label";
import { Busy, QueryState } from "@/components/ui/state";
import { Verdict } from "@/components/ui/verdict";
import { ApiError, api } from "@/lib/api";
import { GetCapabilities } from "@/lib/queries/app";
import { fetching } from "@/lib/queries/cache";
import { GetFreeAgentCalls, GetFreeAgents } from "@/lib/queries/free-agents";
import { AppRoute } from "@/lib/route";
import type { Variant } from "@/lib/tone";
import type { Competition, League, PlayerCall } from "@/lib/types";
import { wire } from "@/lib/wire";

const CALL: Record<PlayerCall["decision"], { label: string; variant: Variant }> = {
  ADD: { label: "Add", variant: "ok" },
  WATCH: { label: "Watch", variant: "warn" },
  PASS: { label: "Pass", variant: "muted" },
};

/** The model's call on one player, under his row — said in words, not only color. */
function CallLine<M>(h: Html.H<M>, call: PlayerCall) {
  const { label, variant } = CALL[call.decision];

  return Verdict(h, {
    label: call.drop ? `${label}, drop ${call.drop}` : label,
    variant,
    reason: call.reason,
    stale: call.stale,
  });
}

/** `kept` with each call in `made` in place of any earlier one on the same player. */
export function withCalls(kept: readonly PlayerCall[], made: readonly PlayerCall[]): PlayerCall[] {
  const replaced = new Set(made.map((call) => call.player_id));

  return [...kept.filter((call) => !replaced.has(call.player_id)), ...made];
}

const FreeAgentsPanelMessage = UiSchema.TaggedEnum({
  UpdatedSearch: { text: Schema.String },
  ClickedPosition: { position: Schema.String },
  ClickedClearFilters: {},
  ClickedSortHeader: { sort: Schema.NullOr(SortState) },
  PickedViewTab: { view: Schema.String },
  ClickedPreviousPage: {},
  ClickedNextPage: {},
  ClickedJudge: {},
  SucceededJudgeFreeAgents: { made: wire<PlayerCall[]>() },
  FailedJudgeFreeAgents: { error: ApiError },
  ClickedPlayer: { id: Schema.String },
  RequestedOpenDrawers: { open: DrawerState },
  RequestedCloseDrawers: {},
});

/**
 * Asks the model for a call on each of `ids`.
 *
 * The judging answers with the calls it made, which go straight into the
 * kept calls of the rows on screen (`shown`, holding `kept`): reading them
 * back is a request for what is already in hand. The kept calls of the other
 * pages read so far are asked again when next shown, since a call outlives
 * its page.
 */
class JudgeFreeAgents extends Command.Service<JudgeFreeAgents>()("league/JudgeFreeAgents", {
  args: {
    competition: Schema.String,
    league: Schema.String,
    ids: Schema.Array(Schema.String),
    shown: Schema.Array(Schema.String),
    kept: wire<readonly PlayerCall[]>(),
  },
  success: FreeAgentsPanelMessage,
  writes: (success, { competition, league, shown, kept }) =>
    success._tag === "SucceededJudgeFreeAgents"
      ? [GetFreeAgentCalls.set({ competition, league, ids: shown }, withCalls(kept, success.made))]
      : [],
  invalidates: () => [GetFreeAgentCalls],
}) {
  static readonly layer = this.toLayer(({ competition, league, ids }) =>
    fetching(() => api.league(competition, league).judgeFreeAgents([...ids])).pipe(
      Effect.match({
        onSuccess: (made) => FreeAgentsPanelMessage.SucceededJudgeFreeAgents({ made }),
        onFailure: (error: ApiError) => FreeAgentsPanelMessage.FailedJudgeFreeAgents({ error }),
      }),
    ),
  );
}

/**
 * Who is still out there.
 *
 * The other half of a roster: what you hold is only half the question, and the
 * half that changes is the wire. Football's pool is four thousand players, so
 * this is a window onto a ranking rather than the ranking itself — which is
 * why the sort, the filters and the paging all happen on the server. Sorting
 * the fifty rows in hand would answer a different question than the one the
 * column header appears to ask.
 *
 * The page's query keeps the table on screen while the next page loads, so
 * paging does not blink the page out and back. No limit is asked for: a page
 * is the server's size, which it says on the page.
 */
const FreeAgentsPanelNoDeps = Html.component({
  name: "FreeAgentsPanel",
  props: Schema.Struct({ competition: wire<Competition>(), league: wire<League>(), route: AppRoute }),
  model: Schema.Struct({
    drawer: Schema.NullOr(DrawerState),
    search: Schema.String,
    position: Schema.String,
    sort: Schema.NullOr(SortState),
    offset: Schema.Number,
    view: Schema.String,
    judgeError: Schema.NullOr(ApiError),
  }),
  message: FreeAgentsPanelMessage,
  queries: {
    page: {
      query: GetFreeAgents,
      args: ({ props, model }) => ({
        competition: props.competition.key,
        league: props.league.league_id,
        offset: model.offset,
        search: model.search,
        position: model.position,
        view: model.view,
        ...toOrder(model.sort),
      }),
    },
    capabilities: { query: GetCapabilities, args: () => ({}) },
    // Kept calls on the rows on screen, read without asking the model: a call
    // outlives the page, and one whose player has moved on since comes back
    // marked stale rather than gone.
    calls: {
      query: GetFreeAgentCalls,
      args: ({ props, queries }) => {
        const ids = shownIds(queries.page);

        return canJudge(queries.capabilities, props.competition) && ids.length > 0
          ? { competition: props.competition.key, league: props.league.league_id, ids }
          : undefined;
      },
    },
  },
}).make({
  init: () => ({ drawer: null, search: "", position: "", sort: null, offset: 0, view: "", judgeError: null }),
  // Any change to what is being asked for starts again at the first page.
  update: {
    UpdatedSearch: ($, { text }) => $.evolve({ search: text, offset: 0 }),
    ClickedPosition: ($, { position }) =>
      $.evolve({ position: (current) => (current === position ? "" : position), offset: 0 }).viewTransition([MARKER]),
    ClickedClearFilters: ($) => $.evolve({ search: "", position: "", offset: 0 }),
    ClickedSortHeader: ($, { sort }) => $.evolve({ sort, offset: 0 }),
    PickedViewTab: ($, { view }) => $.evolve({ view, offset: 0 }).viewTransition([MARKER]),
    ClickedPreviousPage: ($) => $.evolve({ offset: (offset) => Math.max(0, offset - pageSize($.queries.page)) }),
    ClickedNextPage: ($) => $.evolve({ offset: (offset) => offset + pageSize($.queries.page) }),
    // The first rows on screen: the sort has already put the ones worth a
    // call first, whichever sort that is. As many as the server judges at
    // once: a screen's worth of the best.
    ClickedJudge: ($) =>
      $.evolve({ judgeError: null }).run(
        JudgeFreeAgents.make({
          competition: $.props.competition.key,
          league: $.props.league.league_id,
          ids: shownIds($.queries.page).slice(0, judgedAtOnce($.queries.capabilities)),
          shown: shownIds($.queries.page),
          kept: AsyncResult.isSuccess($.queries.calls) ? $.queries.calls.value : [],
        }),
      ),
    SucceededJudgeFreeAgents: ($) => $.evolve({ judgeError: null }),
    FailedJudgeFreeAgents: ($, { error }) => $.evolve({ judgeError: error }),
    ClickedPlayer: ($, { id }) => $.evolve({ drawer: playerDrawer(id) }),
    RequestedOpenDrawers: ($, { open }) => $.evolve({ drawer: open }),
    RequestedCloseDrawers: ($) => $.evolve({ drawer: null }),
  },
  view: (h, model) => {
    const { competition, league } = h.props;
    const result = h.queries.page;
    const judging = h.isRunning(JudgeFreeAgents);
    const judges = canJudge(h.queries.capabilities, competition);
    const calls = new Map((AsyncResult.isSuccess(h.queries.calls) ? h.queries.calls.value : []).map((c) => [c.player_id, c]));
    const filtered = Boolean(model.search || model.position);

    const drawers = Drawers(h, {
      props: { competition: competition.key, league: league.league_id, open: model.drawer },
      onEmit: {
        RequestedOpen: ({ open }) => FreeAgentsPanelMessage.RequestedOpenDrawers({ open }),
        RequestedClose: () => FreeAgentsPanelMessage.RequestedCloseDrawers(),
      },
    });

    if (!AsyncResult.isSuccess(result))
      return h.div.class("contents").children(LeagueHeader(h, { competition, league }), QueryState(h, result, { lines: 6 }), drawers);

    const data = result.value;
    const total = data.total;
    const size = data.limit;
    const shown = data.players.length;
    const offset = model.offset;

    return h.div.class("contents").children(
      LeagueHeader(h, { competition, league }),
      h.div.class("flex flex-col gap-4 p-5").children(
        Card(h).children(
          CardHeader(h).children(
            data.views.length > 0
              ? Tabs(h, {
                  group: "free-agent-views",
                  tabs: [{ id: "", label: "All" }, ...data.views.map((v) => ({ id: v, label: v }))],
                  current: model.view,
                  onPick: (view) => FreeAgentsPanelMessage.PickedViewTab({ view }),
                  class: "-my-1 normal-case tracking-normal",
                })
              : h.span("Available"),
            h.span.class("flex items-center gap-2").children(
              judging && Busy(h).children("judging…"),
              judges &&
                shown > 0 &&
                IconButton(h, {
                  key: "judge",
                  props: {
                    label: `Judge the first ${Math.min(shown, judgedAtOnce(h.queries.capabilities))} shown`,
                    icon: "sparkles",
                    disabled: judging,
                  },
                  onEmit: { Clicked: () => FreeAgentsPanelMessage.ClickedJudge() },
                }),
              h.span(total === 0 ? "none" : `${offset + 1}-${offset + shown} of ${total.toLocaleString()}`),
            ),
          ),
          model.judgeError !== null && ErrorNote(h, { error: model.judgeError, class: "mx-4 my-3", key: "judge" }),

          h.div.class("flex flex-wrap items-center gap-2 border-b border-border px-4 py-3").children(
            // Grows from a floor, so on a phone the chips wrap under it rather than squeezing it shut.
            SearchInput(h, "flex-[1_1_14rem]")
              .attrs({ placeholder: "Search by name, club or status", "aria-label": "Search available players" })
              .value(model.search)
              .on("input", ({ value }) => FreeAgentsPanelMessage.UpdatedSearch({ text: value })),
            // Read off the pool rather than written down: the positions
            // differ per competition, and a list here would be a fourth place to
            // edit. Off the unfiltered pool, so choosing one does not
            // remove the others.
            ...data.positions.map((p) =>
              ToggleChip(h, {
                pressed: model.position === p,
                onClick: FreeAgentsPanelMessage.ClickedPosition({ position: p }),
                group: "free-agent-positions",
                class: "font-mono text-[11px] uppercase tracking-[0.06em]",
              })
                .key(p)
                .children(p),
            ),
            filtered &&
              IconButton(h, {
                key: "clear",
                props: { label: "Clear filters", icon: "x" },
                onEmit: { Clicked: () => FreeAgentsPanelMessage.ClickedClearFilters() },
              }),
          ),

          RosterTable(h, {
            players: [...data.players],
            hints: data.hints,
            empty: {
              title: filtered ? "Nothing matches" : model.view ? `No ${model.view} free agents` : "Nobody available",
              detail: filtered ? "Try another position, or clear the search." : "",
            },
            sort: model.sort,
            onSort: (sort) => FreeAgentsPanelMessage.ClickedSortHeader({ sort }),
            onOpen: (id) => FreeAgentsPanelMessage.ClickedPlayer({ id }),
            detail: (player) => {
              const call = calls.get(player.player_id);

              return call === undefined ? null : [CallLine(h, call)];
            },
          }),

          total > size &&
            h.div.class("flex items-center justify-between border-t border-border px-4 py-3").children(
              Meta(h).children(`Page ${Math.floor(offset / size) + 1} of ${Math.ceil(total / size)}`),
              h.div.class("flex items-center gap-1").children(
                IconButton(h, {
                  key: "previous",
                  props: { label: "Previous page", icon: "chevron-left", disabled: offset === 0 },
                  onEmit: { Clicked: () => FreeAgentsPanelMessage.ClickedPreviousPage() },
                }),
                IconButton(h, {
                  key: "next",
                  props: { label: "Next page", icon: "chevron-right", disabled: offset + size >= total },
                  onEmit: { Clicked: () => FreeAgentsPanelMessage.ClickedNextPage() },
                }),
              ),
            ),
        ),
      ),
      drawers,
    );
  },
});

export const FreeAgentsPanel = FreeAgentsPanelNoDeps.pipe(Component.provide(JudgeFreeAgents.layer));

type Page = AsyncResult.AsyncResult<{ readonly players: readonly { readonly player_id: string }[]; readonly limit: number }, ApiError>;

/** The ids of the rows on screen, kept while the next page loads. */
function shownIds(page: Page): string[] {
  return AsyncResult.isSuccess(page) ? page.value.players.map((p) => p.player_id) : [];
}

/** How many rows a page holds, as the server said on the last one. */
function pageSize(page: Page): number {
  return AsyncResult.isSuccess(page) ? page.value.limit : 0;
}

type Capabilities = AsyncResult.AsyncResult<{ readonly ai: boolean; readonly limits: { readonly judged: number } }, ApiError>;

/** Whether the wire can be judged here: a model configured, and a competition that judges its wire. */
function canJudge(capabilities: Capabilities, competition: Competition): boolean {
  return AsyncResult.isSuccess(capabilities) && capabilities.value.ai && competition.judges_wire;
}

/** As many as the server judges at once: a screen's worth of the best. */
function judgedAtOnce(capabilities: Capabilities): number {
  return AsyncResult.isSuccess(capabilities) ? capabilities.value.limits.judged : 0;
}
