import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Option, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { DrawerState, Drawers } from "@/components/league/drawers";
import { LeagueHeader } from "@/components/league/page-header";
import { WeekPane, WeekStepper, stepWeek, weekShown } from "@/components/league/week-stepper";
import { Label, Meta } from "@/components/ui/label";
import { ListCard, ListHeading, ListRow } from "@/components/ui/list";
import { SlideOver, SlideOverHeader } from "@/components/ui/overlays/dialog";
import { Empty, QueryState } from "@/components/ui/state";
import { GetSeason } from "@/lib/queries/teams";
import { GetGamesOf, GetWeek } from "@/lib/queries/week";
import { AppRoute } from "@/lib/route";
import { kickoff } from "@/lib/times";
import { toneText } from "@/lib/tone";
import type { Competition, League, Match } from "@/lib/types";
import { cn } from "@/lib/utils";
import { wire } from "@/lib/wire";

/** The game's drawer, as the page's drawers know it: one the page draws itself, which a player's Back link returns to. */
const GAME: DrawerState = { kind: "own", key: "game", back: null };

const FixturesPanelMessage = UiSchema.TaggedEnum({
  ClickedGame: { game: wire<Match>() },
  RequestedCloseGame: {},
  ClickedGamePlayer: { id: Schema.String },
  RequestedWeekStepper: { week: Schema.Number },
  RequestedNextPane: {},
  RequestedPreviousPane: {},
  RequestedOpenDrawers: { open: DrawerState },
  RequestedCloseDrawers: {},
});

/**
 * The real games a fantasy week is made of, by kickoff, with whose players are in each and who has a bye.
 *
 * Where the competition pages through the season, so does this: the same
 * stepper, keys and swipe as the Matchup page, against the same range, read
 * from the same summary. Elsewhere it is the week being played, from the
 * league's schedule.
 *
 * A game opens in its own drawer, kept in `game` so it still has something to
 * show while it slides out; a player opened from it replaces it, and his Back
 * link brings it back (`Drawers`, as its `own` kind).
 */
export const FixturesPanel = Html.component({
  name: "FixturesPanel",
  props: Schema.Struct({ competition: wire<Competition>(), league: wire<League>(), route: AppRoute }),
  model: Schema.Struct({ drawer: Schema.NullOr(DrawerState), game: Schema.NullOr(wire<Match>()) }),
  message: FixturesPanelMessage,
  queries: {
    summary: {
      query: GetWeek,
      args: ({ props }) =>
        props.competition.browses_weeks
          ? { competition: props.competition.key, league: props.league.league_id }
          : undefined,
    },
    games: {
      query: GetGamesOf,
      args: ({ props, queries }) => {
        const range = Option.getOrUndefined(AsyncResult.value(queries.summary))?.weeks ?? undefined;
        const { shown } = weekShown(props.competition.browses_weeks ? range : undefined, props.route);

        return shown === undefined
          ? undefined
          : { competition: props.competition.key, league: props.league.league_id, week: shown.week };
      },
    },
    schedule: {
      query: GetSeason,
      args: ({ props }) =>
        props.competition.browses_weeks
          ? undefined
          : { competition: props.competition.key, league: props.league.league_id },
    },
  },
}).make({
  init: () => ({ drawer: null, game: null }),
  update: ($, message) => {
    const range = $.props.competition.browses_weeks
      ? (Option.getOrUndefined(AsyncResult.value($.queries.summary))?.weeks ?? undefined)
      : undefined;

    const { shown } = weekShown(range, $.props.route);
    const step = (to: number) => (shown === undefined ? $.model : $.run(stepWeek($.props.route, shown, to)));

    return FixturesPanelMessage.match(message, {
      ClickedGame: ({ game }) => $.evolve({ game, drawer: GAME }),
      RequestedCloseGame: () => $.evolve({ drawer: null }),
      ClickedGamePlayer: ({ id }) => {
        const game = $.model.game;

        if (game === null) return $.model;

        return $.evolve({
          drawer: { kind: "player", id, back: { label: `${game.away} at ${game.home}`, open: GAME } },
        });
      },
      RequestedWeekStepper: ({ week }) => step(week),
      RequestedNextPane: () => (shown !== undefined && shown.week < shown.last ? step(shown.week + 1) : $.model),
      RequestedPreviousPane: () => (shown !== undefined && shown.week > shown.first ? step(shown.week - 1) : $.model),
      RequestedOpenDrawers: ({ open }) => $.evolve({ drawer: open }),
      RequestedCloseDrawers: () => $.evolve({ drawer: null }),
    });
  },
  view: (h, model) => {
    const { competition, league, route } = h.props;
    const browses = competition.browses_weeks;
    const range = browses ? (Option.getOrUndefined(AsyncResult.value(h.queries.summary))?.weeks ?? undefined) : undefined;
    const { shown } = weekShown(range, route);
    const slate = browses ? Option.getOrUndefined(AsyncResult.value(h.queries.games)) : undefined;
    const rows = browses ? slate?.games : Option.getOrUndefined(AsyncResult.value(h.queries.schedule))?.matches;
    const byes = (browses && slate?.byes) || [];
    const note = (browses && slate?.note) || "";
    const game = model.game;

    return h.div.class("contents").children(
      LeagueHeader(h, {
        competition,
        league,
        children: [
          shown &&
            WeekStepper(h, {
              props: { range: shown, word: competition.week_word },
              onEmit: { RequestedWeek: ({ week }) => FixturesPanelMessage.RequestedWeekStepper({ week }) },
            }),
        ],
      }),
      browses
        ? shown
          ? QueryState(h, h.queries.games, { lines: 6 })
          : QueryState(h, h.queries.summary, { lines: 6 })
        : QueryState(h, h.queries.schedule, { lines: 6 }),
      rows !== undefined && rows.length === 0 && Empty(h, { title: `No games this ${competition.week_word}` }),
      rows !== undefined &&
        rows.length > 0 &&
        WeekPane(h, {
          props: {
            week: shown?.week ?? 0,
            pending: browses && h.queries.games.waiting,
            swipe: true,
            class: "touch-pan-y p-5",
          },
          onEmit: {
            RequestedNext: () => FixturesPanelMessage.RequestedNextPane(),
            RequestedPrevious: () => FixturesPanelMessage.RequestedPreviousPane(),
          },
          slots: {
            content: Games(h, { rows, byes, note, onOpen: (open) => FixturesPanelMessage.ClickedGame({ game: open }) }),
          },
        }),
      SlideOver(h, {
        key: "game",
        open: model.drawer?.kind === "own" && game !== null,
        onClose: FixturesPanelMessage.RequestedCloseGame(),
        label: game ? `${game.away} at ${game.home}` : "Game",
        class: "max-w-lg border-l border-border",
        children: [
          game &&
            GameDetail(h, {
              game,
              onClose: FixturesPanelMessage.RequestedCloseGame(),
              onOpen: (id) => FixturesPanelMessage.ClickedGamePlayer({ id }),
            }),
        ],
      }),
      Drawers(h, {
        props: { competition: competition.key, league: league.league_id, open: model.drawer },
        onEmit: {
          RequestedOpen: ({ open }) => FixturesPanelMessage.RequestedOpenDrawers({ open }),
          RequestedClose: () => FixturesPanelMessage.RequestedCloseDrawers(),
        },
      }),
    );
  },
});

/** Who you and your opponent have in one game; a player opens in its place, with the way back to it. */
function GameDetail<M>(h: Html.H<M>, { game, onClose, onOpen }: { game: Match; onClose: M; onOpen: (id: string) => M }) {
  return h.div.class("contents").children(
    SlideOverHeader(h, {
      title: [`${game.away} at ${game.home}`],
      meta: [game.kickoff ? kickoff(game.kickoff) : game.label, game.detail].filter(Boolean).join(" · "),
      onClose,
    }),
    h.div.class("flex flex-col gap-4 p-5").children(
      [
        { title: "Yours", players: game.yours },
        { title: "Your opponent's", players: game.theirs },
      ].flatMap((side) =>
        side.players.length === 0
          ? []
          : ListCard(h, {
              title: side.title,
              count: `${side.players.length}`,
              children: side.players.map((p) =>
                ListRow(h, { onClick: onOpen(p.player_id) })
                  .key(p.player_id)
                  .children(
                    h.span.class("min-w-0 flex-1 truncate").children(p.name),
                    Meta(h, { class: "shrink-0" }).children(p.detail),
                  ),
              ),
            }).key(side.title),
      ),
    ),
  );
}

/** When a game starts: its kickoff in the viewer's zone where known, the day the schedule gives otherwise. */
const slot = (game: Match) => (game.kickoff ? kickoff(game.kickoff) : game.label);

/**
 * The week's games under one heading per kickoff, so a time is said once
 * rather than on every row of a Sunday. Rows arrive in kickoff order, so a
 * slot is a run of them.
 */
export function Games<M>(
  h: Html.H<M>,
  {
    rows,
    byes = [],
    note = "",
    onOpen,
  }: {
    rows: readonly Match[];
    /** Clubs with no game this week. */
    byes?: readonly string[] | undefined;
    /** Why the list is not to be read as complete — a schedule not final yet; empty for most weeks. */
    note?: string | undefined;
    onOpen?: ((game: Match) => M) | undefined;
  },
) {
  return ListCard(h, {
    title: "Fixtures",
    count: `${rows.length} games`,
    children: [
      note &&
        ListRow(h)
          .key("note")
          .children(h.span.attr("class", cn("min-w-0 flex-1 text-[12.5px]", toneText("warning"))).children(note)),
      byes.length > 0 &&
        ListRow(h)
          .key("byes")
          .children(
            Label(h, { class: "shrink-0" }).children("Byes"),
            h.span.class("min-w-0 flex-1 font-mono text-[12px]").children(byes.join(", ")),
          ),
      ...rows.flatMap((row, i) => {
        const before = rows[i - 1];
        const key = `${row.home}-${row.away}-${i}`;

        return [
          (!before || slot(before) !== slot(row)) && ListHeading(h).key(`slot-${key}`).children(slot(row)),
          ListRow(h, {
            class: "flex-col items-stretch gap-1",
            // A game opens where somebody's players are in it: the rest have nothing to show.
            onClick: onOpen && (row.yours.length || row.theirs.length) ? onOpen(row) : undefined,
          })
            .key(key)
            .children(
              h.div.class("flex items-baseline gap-3").children(
                h.span
                  .class("min-w-0 flex-1 font-mono text-[12.5px]")
                  .children(
                    Side(h, { club: row.away, score: row.away_score, other: row.home_score }),
                    " ",
                    h.span.class("text-muted-foreground").children("at"),
                    " ",
                    Side(h, { club: row.home, score: row.home_score, other: row.away_score }),
                  ),
                row.detail &&
                  h.span
                    .attr("class", cn("shrink-0 font-mono text-[11px]", toneText(row.tone, "text-muted-foreground")))
                    .children(row.detail),
              ),
              Holders(h, row),
            ),
        ];
      }),
    ],
  });
}

/** Whose players are in a game, by name: yours, then your opponent's, each side labelled in words. */
function Holders<M>(h: Html.H<M>, game: Match) {
  const sides = [
    { label: "You", players: game.yours, tone: "" },
    { label: "Opp", players: game.theirs, tone: "text-muted-foreground" },
  ].filter((side) => side.players.length > 0);

  if (sides.length === 0) return null;

  return h.div.class("flex flex-wrap gap-x-4 gap-y-0.5 text-[12px]").children(
    sides.map((side) =>
      h.span
        .key(side.label)
        .class("min-w-0")
        .children(
          Label(h, { class: "mr-1.5" }).children(side.label),
          h.span.attr("class", side.tone).children(side.players.map((p) => p.name).join(", ")),
        ),
    ),
  );
}

/** A club, and its score once the game has kicked off; the side ahead in weight, which reads without color. */
function Side<M>(h: Html.H<M>, { club, score, other }: { club: string; score: number | null; other: number | null }) {
  if (score === null) return club;

  const ahead = other !== null && score > other;

  return h.span.attr("class", cn(ahead && "font-semibold")).children(club, " ", h.span.class("tabular-nums").children(String(score)));
}
