import { Command, Component, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Effect, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { ActionList } from "@/components/league/actions";
import { Categories } from "@/components/league/categories";
import { DayStepper, dayAsked, stepDay } from "@/components/league/day-stepper";
import { DrawerState, Drawers, comparisonDrawer, playerDrawer } from "@/components/league/drawers";
import { LineupCard, SideCard, rowsOf } from "@/components/league/lineup";
import { LeagueHeader } from "@/components/league/page-header";
import { staleVerdicts } from "@/components/league/verdicts";
import { WeekPane, WeekStepper, stepWeek, weekShown } from "@/components/league/week-stepper";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { IconButton } from "@/components/ui/controls/icon-button";
import { ErrorNote } from "@/components/ui/error-note";
import { StatCells, StatGrid, StatList, StatStrip } from "@/components/ui/stat";
import { Busy, QueryState } from "@/components/ui/state";
import { ApiError, api } from "@/lib/api";
import type { Comparing } from "@/lib/comparing";
import { dayLabel, dayNumber } from "@/lib/days";
import { GetCapabilities } from "@/lib/queries/app";
import { fetching, type Answer, type LeagueApi } from "@/lib/queries/cache";
import { GetUntouchables } from "@/lib/queries/teams";
import { GetDayOf, GetJudgment, GetWeek, GetWeekOf } from "@/lib/queries/week";
import { AppRoute } from "@/lib/route";
import { moment } from "@/lib/times";
import type { Competition, League, Summary } from "@/lib/types";
import { wire } from "@/lib/wire";

const MatchupMessage = UiSchema.TaggedEnum({
  RequestedStepperWeek: { week: Schema.Number },
  RequestedNextWeekPane: {},
  RequestedPreviousWeekPane: {},
  RequestedStepperDay: { day: Schema.String },
  ClickedPlayer: { id: Schema.String },
  RequestedOpenActionPlayer: { id: Schema.String },
  RequestedCompareActions: { comparing: wire<Comparing>() },
  RequestedOpenDrawer: { open: DrawerState },
  RequestedCloseDrawers: {},
  ClickedJudge: {},
  /** What the kept judgment says now: whether the week has moved on from it, once it is read for this league. */
  ChangedJudgment: { due: Schema.Boolean },
  SucceededJudgeWeek: {},
  FailedJudgeWeek: { error: ApiError },
});

/**
 * Judges the week's to-do list. The week carries each item's verdict, so a
 * new judgment is read back through it as well as through the judgment's own
 * time and moves.
 */
class JudgeWeek extends Command.Service<JudgeWeek>()("matchup/JudgeWeek", {
  args: { competition: Schema.String, league: Schema.String },
  success: MatchupMessage,
  invalidates: ({ competition, league }) => [
    GetJudgment.entry({ competition, league }),
    GetWeek.entry({ competition, league }),
  ],
}) {
  static readonly layer = this.toLayer(({ competition, league }) =>
    fetching(() => api.league(competition, league).judge()).pipe(
      Effect.match({
        onSuccess: () => MatchupMessage.SucceededJudgeWeek(),
        onFailure: (error) => MatchupMessage.FailedJudgeWeek({ error }),
      }),
    ),
  );
}

const MatchupPanelProps = Schema.Struct({
  competition: wire<Competition>(),
  league: wire<League>(),
  /** The address, which names the week (`?week=`) and the day (`?day=`) shown. */
  route: AppRoute,
});

type MatchupPanelProps = typeof MatchupPanelProps.Type;

type WeekResult = AsyncResult.AsyncResult<Answer<LeagueApi["week"]>, ApiError>;

/** The value of a query that has one, kept or fresh; else null. */
const valueOf = <A, E>(result: AsyncResult.AsyncResult<A, E>): A | null =>
  AsyncResult.isSuccess(result) ? result.value : null;

/** The league a query of this page is addressed by. */
const at = (props: MatchupPanelProps) => ({ competition: props.competition.key, league: props.league.league_id });

/**
 * The week shown: the summary's own where it is the one being played, any
 * other asked for by number. Only where the competition pages through weeks.
 */
function weekOf(props: MatchupPanelProps, week: WeekResult) {
  const range = props.competition.browses_weeks ? (valueOf(week)?.weeks ?? undefined) : undefined;

  return weekShown(range, props.route);
}

/**
 * The matchup: where you stand, what you are fielding, and who against — this week, or any other.
 *
 * Complete without a model: everything is read or computed from league state,
 * so the page is whole the moment it opens. Where a model is configured it
 * annotates what is already here — Judge fills each to-do with a verdict and
 * adds the moves the list missed, in place — rather than producing a page of
 * its own to be read beside this one. The last judgment shows on load, from
 * where it was kept, and is asked again only once the week has moved on
 * from it — the server's `due`, never merely a reload.
 *
 * Judged again on arrival where the server says the week has moved on from
 * the kept judgment — an item it never saw, or half a day of changes. Once
 * per league for as long as the page is open (`asked`): a judgment that
 * fails, or comes back still due, is not retried in a loop.
 *
 * Another week opens from the stepper, the arrow keys or a swipe, and is named
 * in the address (`?week=7`) so it can be linked and Back returns from it. It
 * shows that week's lineups and score and no to-do list, which is only ever
 * about the week being played.
 *
 * Where lineups are set day by day (`browses_days`), the lineups are one day's
 * — today's in the week being played, else the week's first — with a stepper of
 * its own and the arrow keys moving through the week's days (`?day=`), and the
 * day's score beside the week's.
 */
const MatchupPanelNoDeps = Html.component({
  name: "MatchupPanel",
  props: MatchupPanelProps,
  model: Schema.Struct({
    drawer: Schema.NullOr(DrawerState),
    /** The leagues judged on arrival, as `competition:league`: each is asked once. */
    asked: Schema.Array(Schema.String),
    judging: Schema.Boolean,
    failed: Schema.NullOr(ApiError),
  }),
  message: MatchupMessage,
  queries: {
    capabilities: { query: GetCapabilities, args: () => ({}) },
    week: { query: GetWeek, args: ({ props }) => at(props) },
    // The week being played is the summary's; any other is asked for by
    // number. The last week stays up while the next loads (`waiting`),
    // rather than the page blanking on every step.
    other: {
      query: GetWeekOf,
      args: ({ props, queries }) => {
        const { browsing } = weekOf(props, queries.week);

        return browsing === null ? undefined : { ...at(props), week: browsing };
      },
    },
    // The lineups, a day at a time where they are set by the day: asked for once the week shown is known.
    day: {
      query: GetDayOf,
      args: ({ props, queries }) => {
        const { shown } = weekOf(props, queries.week);

        return props.competition.browses_days && shown !== undefined
          ? { ...at(props), week: shown.week, day: dayAsked(props.route) }
          : undefined;
      },
    },
    untouchables: { query: GetUntouchables, args: ({ props }) => at(props) },
    // The last judgment, read without asking the model anything: judging is a
    // click, and a reload should not throw the answer away.
    judgment: {
      query: GetJudgment,
      args: ({ props, queries }) =>
        valueOf(queries.capabilities)?.ai === true && Boolean(valueOf(queries.week)?.actions) ? at(props) : undefined,
      // Only an answer for the league now shown: one kept from the last while
      // this one's is asked says nothing about this one.
      onChange: (result) =>
        MatchupMessage.ChangedJudgment({
          due: AsyncResult.isSuccess(result) && !result.waiting && result.value?.due === true,
        }),
    },
  },
  restore: false,
}).make({
  init: () => ({ drawer: null, asked: [], judging: false, failed: null }),
  update: ($, message) => {
    const { route } = $.props;
    const { shown } = weekOf($.props, $.queries.week);
    const judge = () => $.evolve({ judging: true, failed: null }).run(JudgeWeek.make(at($.props)));

    return MatchupMessage.match(message, {
      RequestedStepperWeek: ({ week }) => (shown ? $.run(stepWeek(route, shown, week)) : $.model),
      RequestedNextWeekPane: () =>
        shown && shown.week < shown.last ? $.run(stepWeek(route, shown, shown.week + 1)) : $.model,
      RequestedPreviousWeekPane: () =>
        shown && shown.week > shown.first ? $.run(stepWeek(route, shown, shown.week - 1)) : $.model,
      RequestedStepperDay: ({ day }) => {
        const days = valueOf($.queries.day)?.days;

        return days ? $.run(stepDay(route, days, day)) : $.model;
      },
      ClickedPlayer: ({ id }) => $.evolve({ drawer: playerDrawer(id) }),
      RequestedOpenActionPlayer: ({ id }) => $.evolve({ drawer: playerDrawer(id) }),
      RequestedCompareActions: ({ comparing }) =>
        $.evolve({ drawer: comparisonDrawer(comparing.ids, { title: comparing.title, tags: comparing.tags }) }),
      RequestedOpenDrawer: ({ open }) => $.evolve({ drawer: open }),
      RequestedCloseDrawers: () => $.evolve({ drawer: null }),
      ClickedJudge: judge,
      ChangedJudgment: ({ due }) => {
        const scope = `${$.props.competition.key}:${$.props.league.league_id}`;

        if (!due || $.model.judging || $.model.asked.includes(scope)) return $.model;

        return judge().evolve({ asked: (asked) => [...asked, scope] });
      },
      SucceededJudgeWeek: () => $.evolve({ judging: false }),
      FailedJudgeWeek: ({ error }) => $.evolve({ judging: false, failed: error }),
    });
  },
  view: (h, model) => {
    const { competition, league } = h.props;
    const ai = valueOf(h.queries.capabilities)?.ai ?? false;
    const daily = competition.browses_days;
    const { browsing, shown: onWeek } = weekOf(h.props, h.queries.week);
    const shownResult = browsing === null ? h.queries.week : h.queries.other;
    const shown = valueOf(shownResult);
    const dayResult = h.queries.day;
    const day = valueOf(dayResult);
    const lineups = daily ? day : shown;
    const days = daily ? (day?.days ?? undefined) : undefined;
    const marked = valueOf(h.queries.untouchables)?.player_ids ?? [];
    const untouchable = (id: string) => marked.includes(id);
    const judgment = valueOf(h.queries.judgment);
    const onOpen = (id: string) => MatchupMessage.ClickedPlayer({ id });

    return h.div.class("contents").children(
      // The week is what this page is about, so it belongs in the header
      // rather than a row down among the figures.
      LeagueHeader(h, {
        competition,
        league,
        meta: [shown?.weeks ? undated(shown.window) : shown?.window, league.detail].filter(Boolean).join(" · "),
        children: [
          onWeek &&
            WeekStepper(h, {
              props: { range: onWeek, word: competition.week_word ?? undefined, keys: !days },
              onEmit: { RequestedWeek: ({ week }) => MatchupMessage.RequestedStepperWeek({ week }) },
            }),
          days &&
            DayStepper(h, {
              props: { range: days },
              onEmit: { RequestedDay: ({ day: to }) => MatchupMessage.RequestedStepperDay({ day: to }) },
            }),
        ],
      }),
      // Only what no card below says: the score once there is one, the chances.
      StatStrip(h, shown?.headline ?? []),
      QueryState(h, shownResult, { lines: 4 }),
      shown &&
        WeekPane(h, {
          key: "week",
          props: {
            week: shown.weeks?.week ?? 0,
            pending: AsyncResult.isSuccess(shownResult) && shownResult.waiting,
            swipe: onWeek !== undefined,
            // Two across once the page has the room: what to do beside the
            // lineups it acts on, rather than a to-do stretched past reading.
            class:
              "grid touch-pan-y grid-cols-1 items-start gap-4 p-5 @min-[96rem]:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]",
          },
          onEmit: {
            RequestedNext: () => MatchupMessage.RequestedNextWeekPane(),
            RequestedPrevious: () => MatchupMessage.RequestedPreviousWeekPane(),
          },
          slots: {
            content: [
              h.div.class("flex min-w-0 flex-col gap-4 empty:hidden").children(
                model.failed !== null && ErrorNote(h, { error: model.failed, class: "m-0", key: "judge" }),
                shown.actions &&
                  ActionList(h, {
                    props: {
                      competition,
                      league: league.league_id,
                      actions: shown.actions,
                      suggested: judgment?.answer.moves,
                      decides: true,
                      asks: ai,
                    },
                    onEmit: {
                      RequestedOpenPlayer: ({ id }) => MatchupMessage.RequestedOpenActionPlayer({ id }),
                      RequestedCompare: ({ comparing }) => MatchupMessage.RequestedCompareActions({ comparing }),
                    },
                    slots: {
                      // Only where a model is configured: a control that cannot
                      // work would be an offer and then a refusal.
                      aside:
                        ai &&
                        h.span.class("flex items-center gap-2 normal-case tracking-normal").children(
                          judgment &&
                            !model.judging &&
                            JudgedAt(h, { at: judgment.answered_at, stale: staleVerdicts(shown.actions) }),
                          model.judging && Busy(h).children("judging…"),
                          IconButton(h, {
                            key: "judge",
                            props: {
                              label: judgment ? "Judge again" : "Judge this list",
                              icon: "sparkles",
                              disabled: model.judging,
                            },
                            onEmit: { Clicked: () => MatchupMessage.ClickedJudge() },
                          }),
                        ),
                    },
                  }),
                shown.categories.length > 0 &&
                  Categories(h, { lines: shown.categories, title: days ? "Week" : undefined }),
                days &&
                  day &&
                  day.categories.length > 0 &&
                  Categories(h, { lines: day.categories, title: dayLabel(days.day) }),
              ),
              h.div.class("min-w-0 @min-[96rem]:col-start-2 @min-[96rem]:row-span-2 @min-[96rem]:row-start-1").children(
                h.div.class("@container flex flex-col gap-4").children(
                  daily && QueryState(h, dayResult, { lines: 4 }),
                  lineups &&
                    WeekPane(h, {
                      key: "day",
                      props: {
                        week: days ? dayNumber(days.day) : 0,
                        pending: daily && AsyncResult.isSuccess(dayResult) && dayResult.waiting,
                        class: "flex flex-col gap-4",
                      },
                      slots: { content: Lineups(h, { lineups, days: days !== undefined, onOpen, untouchable }) },
                    }),
                ),
              ),
              // Back in the first column under the to-do on a wide page; after the
              // lineups, as before, on a narrow one.
              h.div.class("flex min-w-0 flex-col gap-4 empty:hidden @min-[96rem]:col-start-1").children(
                shown.boosts &&
                  shown.boosts.stats.length > 0 &&
                  Card(h).children(
                    CardHeader(h).children(h.span(shown.boosts.title), shown.boosts.note && h.span(shown.boosts.note)),
                    StatGrid(h, shown.boosts.stats),
                  ),
                // Only what a row cannot say for itself: a blank or a double gameweek
                // changes what a whole club's players are worth.
                shown.fixtures.length > 0 &&
                  Card(h).children(
                    CardHeader(h).children(h.span("Watch out for")),
                    StatList(h, { stats: shown.fixtures, class: "px-4 py-1" }),
                  ),
                !shown.opponent &&
                  Badge(h, { variant: "muted", appearance: "label" }).children(
                    `No opponent this ${competition.week_word ?? "week"}`,
                  ),
              ),
            ],
          },
        }),
      Drawers(h, {
        props: { competition: competition.key, league: league.league_id, open: model.drawer },
        onEmit: {
          RequestedOpen: ({ open }) => MatchupMessage.RequestedOpenDrawer({ open }),
          RequestedClose: () => MatchupMessage.RequestedCloseDrawers(),
        },
      }),
    );
  },
});

export const MatchupPanel = MatchupPanelNoDeps.pipe(Component.provide(JudgeWeek.layer));

type Message = typeof MatchupMessage.Type;

/** Both sides of the matchup, or your lineup alone where there is nobody across; with the day's own score where it is a day's. */
function Lineups(
  h: Html.H<Message>,
  {
    lineups,
    days,
    onOpen,
    untouchable,
  }: { lineups: Summary; days: boolean; onOpen: (id: string) => Message; untouchable: (id: string) => boolean },
) {
  const { mine, opponent } = lineups;

  return [
    // The day's own score and starts, under the week's in the header.
    days && lineups.headline.length > 0 && StatCells(h, { stats: lineups.headline, class: "rounded-lg border border-border" }),
    opponent
      ? // Side by side once their column fits two (about 470px each, what an
        // NBA row's per-game line needs), stacked before that: a 1920px screen
        // has the to-do beside them, not room for both across. Both sides draw
        // the same columns and row heights, read from either, so slot N sits beside slot N.
        h.div.class("grid grid-cols-1 gap-4 @min-[60rem]:grid-cols-2").children(
          SideCard(h, { side: mine, label: "You", onOpen, untouchable, rows: rowsOf(mine, opponent) }),
          SideCard(h, { side: opponent, label: "Opponent", onOpen, rows: rowsOf(mine, opponent) }),
        )
      : LineupCard(h, {
          title: "Your lineup",
          lineup: mine?.lineup ?? [],
          bench: mine?.bench ?? [],
          reserve: mine?.reserve ?? [],
          openSpots: mine?.open_spots ?? 0,
          onOpen,
          untouchable,
        }),
  ];
}

/**
 * When the list was last judged, and — once for the whole list rather than on
 * every row — that some of it has changed since. Said in words, with the
 * color only to find it.
 */
export function JudgedAt<M>(h: Html.H<M>, { at: when, stale }: { at: string; stale: boolean }) {
  return h.span.class("font-normal").children(`judged ${moment(when)}`, stale && h.span.class("text-warn").children(" · stale"));
}

/** A window without its leading "Week 11", "GW 11" or "Gameweek 11": the stepper already says which. */
export function undated(window: string): string {
  return window.replace(/^(Week|GW|Gameweek) \d+( · )?/, "");
}
